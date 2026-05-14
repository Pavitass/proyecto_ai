/**
 * Panel "Plan en vivo": bottom sheet con pasos, "no me funcionó", kanban y sliders.
 * Depende de: marked/DOMPurify no requeridos aquí (solo HTML escapado).
 */
(function (global) {
  const UI_BLOCK = /```helpdesk-ui\s*([\s\S]*?)```/i;

  function stripHelpdeskUi(text) {
    if (!text) return "";
    return text.replace(UI_BLOCK, "").trim();
  }

  function parseHelpdeskUi(text) {
    if (!text) return null;
    const m = text.match(UI_BLOCK);
    if (!m) return null;
    try {
      return JSON.parse(m[1].trim());
    } catch {
      return null;
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function extractPlanLines(md) {
    const out = [];
    if (!md) return out;
    const h = md.match(/^##\s*plan\b[^\n]*/im);
    if (!h) return out;
    const start = md.indexOf(h[0]) + h[0].length;
    const tail = md.slice(start);
    const n2 = tail.search(/^##\s+/m);
    const chunk = (n2 >= 0 ? tail.slice(0, n2) : tail).split("\n");
    for (const raw of chunk) {
      const line = raw.trim();
      const num = /^(\d+)\.\s+(.+)$/.exec(line);
      if (num) {
        out.push({ kind: "num", n: parseInt(num[1], 10), text: num[2].trim() });
        continue;
      }
      const task = /^-\s+\[([ xX])\]\s+(.+)$/.exec(line);
      if (task) {
        out.push({ kind: "task", checked: task[1].toLowerCase() === "x", text: task[2].trim() });
      }
    }
    return out;
  }

  let deps = {
    getThreadId: function () {
      return "";
    },
    chat: async function () {
      throw new Error("LiveSheet.init no configurado");
    },
    onAfterRender: null,
  };

  let kanbanState = null;

  function el(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }

  function getShell() {
    return document.getElementById("liveSheet");
  }

  function setExpanded(on) {
    const sh = getShell();
    if (!sh) return;
    sh.classList.toggle("live-sheet--expanded", !!on);
    sh.setAttribute("aria-expanded", on ? "true" : "false");
    const tab = document.getElementById("liveSheetTab");
    if (tab) tab.setAttribute("aria-expanded", on ? "true" : "false");
    document.querySelector(".main")?.classList.toggle("live-sheet-expanded", !!on);
  }

  function clearPanels() {
    ["liveSheetPlan", "liveSheetKanban", "liveSheetSliders"].forEach((id) => {
      const n = document.getElementById(id);
      if (n) n.innerHTML = "";
    });
  }

  function renderPlan(plan) {
    const host = document.getElementById("liveSheetPlan");
    if (!host) return;
    host.innerHTML = "";
    if (!plan.length) {
      host.innerHTML = "<p class=\"live-sheet-muted\">No hay sección «Plan de acción» detectada en la última respuesta.</p>";
      return;
    }
    const wrap = el("<div class=\"live-plan\"></div>");
    plan.forEach((p) => {
      if (p.kind === "num") {
        const row = el(
          "<div class=\"live-step\" data-step=\"" +
            p.n +
            "\">" +
            "<span class=\"live-step-badge\">" +
            p.n +
            "</span>" +
            "<div class=\"live-step-body\">" +
            "<div class=\"live-step-text\"></div>" +
            "<details class=\"live-step-fail\">" +
            "<summary>No me funcionó</summary>" +
            "<textarea class=\"live-step-note\" rows=\"2\" placeholder=\"Qué viste (error, pantalla, etc.)\"></textarea>" +
            "<button type=\"button\" class=\"btn-ghost btn-tiny live-step-send\">Enviar al agente</button>" +
            "</details>" +
            "</div></div>"
        );
        row.querySelector(".live-step-text").textContent = p.text;
        const send = row.querySelector(".live-step-send");
        send.addEventListener("click", async () => {
          const note = row.querySelector(".live-step-note").value.trim();
          const msg =
            "El paso " +
            p.n +
            ' del plan ("' +
            p.text.slice(0, 120) +
            (p.text.length > 120 ? "…" : "") +
            '") no me funcionó.' +
            (note ? " Detalle: " + note : "");
          send.disabled = true;
          try {
            await deps.chat({
              message: msg,
              thread_id: deps.getThreadId(),
              screenshots: [],
              interaction: {
                type: "step_failed",
                payload: { step: p.n, step_text: p.text, note: note || null },
              },
            });
            row.querySelector("details").open = false;
          } catch (e) {
            alert(e.message || String(e));
          }
          send.disabled = false;
        });
        wrap.appendChild(row);
      } else if (p.kind === "task") {
        const row = el("<label class=\"live-task\"><input type=\"checkbox\" /> <span></span></label>");
        const cb = row.querySelector("input");
        cb.checked = p.checked;
        row.querySelector("span").textContent = p.text;
        cb.addEventListener("change", async () => {
          try {
            await deps.chat({
              message:
                "He " +
                (cb.checked ? "marcado" : "desmarcado") +
                ' la tarea: "' +
                p.text.slice(0, 200) +
                '".',
              thread_id: deps.getThreadId(),
              screenshots: [],
              interaction: {
                type: "checklist_update",
                payload: { text: p.text, checked: cb.checked },
              },
            });
          } catch (e) {
            alert(e.message || String(e));
            cb.checked = !cb.checked;
          }
        });
        wrap.appendChild(row);
      }
    });
    host.appendChild(wrap);
  }

  function cloneKanban(ui) {
    if (!ui || !ui.kanban || !Array.isArray(ui.kanban.columns)) return null;
    return JSON.parse(JSON.stringify(ui.kanban));
  }

  function renderKanban(ui) {
    const host = document.getElementById("liveSheetKanban");
    if (!host) return;
    host.innerHTML = "";
    kanbanState = cloneKanban(ui);
    if (!kanbanState) return;
    const title = el("<h4 class=\"live-sheet-h\">Tablero (arrastra tarjetas)</h4>");
    host.appendChild(title);
    const board = el("<div class=\"live-kanban\"></div>");
    kanbanState.columns.forEach((col) => {
      const colEl = el(
        "<div class=\"live-kcol\" data-col-id=\"" +
          escapeHtml(col.id) +
          "\"><div class=\"live-kcol-title\"></div><div class=\"live-kcol-drop\"></div></div>"
      );
      colEl.querySelector(".live-kcol-title").textContent = col.title || col.id;
      const drop = colEl.querySelector(".live-kcol-drop");
      drop.addEventListener("dragover", (e) => {
        e.preventDefault();
        drop.classList.add("live-kcol-drop--over");
      });
      drop.addEventListener("dragleave", () => drop.classList.remove("live-kcol-drop--over"));
      drop.addEventListener("drop", (e) => {
        e.preventDefault();
        drop.classList.remove("live-kcol-drop--over");
        const cardId = e.dataTransfer.getData("text/card-id");
        const fromCol = e.dataTransfer.getData("text/from-col");
        const toCol = col.id;
        if (!cardId || !fromCol || fromCol === toCol) return;
        moveCard(fromCol, toCol, cardId);
        renderKanbanCardsOnly();
      });
      (col.cards || []).forEach((card) => {
        drop.appendChild(makeCardEl(card, col.id));
      });
      board.appendChild(colEl);
    });
    host.appendChild(board);
    const btn = el(
      "<button type=\"button\" class=\"btn-ghost live-kanban-send\">Informar tablero al agente</button>"
    );
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await deps.chat({
          message: "Actualicé el tablero Kanban en el panel en vivo; incorpora el nuevo orden a tu plan.",
          thread_id: deps.getThreadId(),
          screenshots: [],
          interaction: { type: "kanban_update", payload: { kanban: kanbanState } },
        });
      } catch (e) {
        alert(e.message || String(e));
      }
      btn.disabled = false;
    });
    host.appendChild(btn);
  }

  function makeCardEl(card, colId) {
    const c = el(
      "<div class=\"live-kcard\" draggable=\"true\"><span class=\"live-kcard-text\"></span></div>"
    );
    c.dataset.cardId = card.id;
    c.dataset.fromCol = colId;
    c.querySelector(".live-kcard-text").textContent = card.text || card.id;
    c.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/card-id", card.id);
      e.dataTransfer.setData("text/from-col", colId);
      e.dataTransfer.effectAllowed = "move";
    });
    return c;
  }

  function moveCard(fromColId, toColId, cardId) {
    if (!kanbanState) return;
    let card = null;
    const fromCol = kanbanState.columns.find((c) => c.id === fromColId);
    const toCol = kanbanState.columns.find((c) => c.id === toColId);
    if (!fromCol || !toCol) return;
    fromCol.cards = fromCol.cards || [];
    toCol.cards = toCol.cards || [];
    const idx = fromCol.cards.findIndex((x) => x.id === cardId);
    if (idx < 0) return;
    card = fromCol.cards.splice(idx, 1)[0];
    toCol.cards.push(card);
  }

  function renderKanbanCardsOnly() {
    const host = document.getElementById("liveSheetKanban");
    if (!host || !kanbanState) return;
    const board = host.querySelector(".live-kanban");
    if (!board) return;
    board.innerHTML = "";
    kanbanState.columns.forEach((col) => {
      const colEl = el(
        "<div class=\"live-kcol\" data-col-id=\"" +
          escapeHtml(col.id) +
          "\"><div class=\"live-kcol-title\"></div><div class=\"live-kcol-drop\"></div></div>"
      );
      colEl.querySelector(".live-kcol-title").textContent = col.title || col.id;
      const drop = colEl.querySelector(".live-kcol-drop");
      drop.addEventListener("dragover", (e) => {
        e.preventDefault();
        drop.classList.add("live-kcol-drop--over");
      });
      drop.addEventListener("dragleave", () => drop.classList.remove("live-kcol-drop--over"));
      drop.addEventListener("drop", (e) => {
        e.preventDefault();
        drop.classList.remove("live-kcol-drop--over");
        const cardId = e.dataTransfer.getData("text/card-id");
        const fromCol = e.dataTransfer.getData("text/from-col");
        const toCol = col.id;
        if (!cardId || !fromCol) return;
        moveCard(fromCol, toCol, cardId);
        renderKanbanCardsOnly();
      });
      (col.cards || []).forEach((card) => {
        drop.appendChild(makeCardEl(card, col.id));
      });
      board.appendChild(colEl);
    });
  }

  function renderSliders(ui) {
    const host = document.getElementById("liveSheetSliders");
    if (!host) return;
    host.innerHTML = "";
    const sliders = ui && Array.isArray(ui.sliders) ? ui.sliders : [];
    if (!sliders.length) return;
    host.appendChild(el("<h4 class=\"live-sheet-h\">Ajustes rápidos</h4>"));
    const box = el("<div class=\"live-sliders\"></div>");
    sliders.forEach((s, i) => {
      const id = s.id || "s" + i;
      const row = el(
        "<div class=\"live-slider\" data-slider-id=\"" +
          escapeHtml(id) +
          "\"><label class=\"live-slider-label\"></label>" +
          "<input type=\"range\" /><span class=\"live-slider-val\"></span></div>"
      );
      row.querySelector("label").textContent = s.label || id;
      const inp = row.querySelector("input");
      const min = Number.isFinite(s.min) ? s.min : 0;
      const max = Number.isFinite(s.max) ? s.max : 10;
      const val = Number.isFinite(s.value) ? s.value : min;
      inp.min = min;
      inp.max = max;
      inp.value = val;
      const span = row.querySelector(".live-slider-val");
      span.textContent = String(val);
      inp.addEventListener("input", () => {
        span.textContent = inp.value;
      });
      box.appendChild(row);
    });
    const btn = el(
      "<button type=\"button\" class=\"btn-ghost live-slider-send\">Enviar valores al agente</button>"
    );
    btn.addEventListener("click", async () => {
      const values = {};
      box.querySelectorAll(".live-slider").forEach((row) => {
        const sid = row.dataset.sliderId;
        const inp = row.querySelector("input[type=range]");
        if (sid && inp) values[sid] = Number(inp.value);
      });
      btn.disabled = true;
      try {
        await deps.chat({
          message: "Te envío los valores de los sliders del panel en vivo.",
          thread_id: deps.getThreadId(),
          screenshots: [],
          interaction: { type: "slider_values", payload: { values: values } },
        });
      } catch (e) {
        alert(e.message || String(e));
      }
      btn.disabled = false;
    });
    host.appendChild(box);
    host.appendChild(btn);
  }

  function afterAssistantReply(rawReply, assistantWrapEl) {
    const shell = getShell();
    if (!shell) return;
    const clean = stripHelpdeskUi(rawReply);
    const ui = parseHelpdeskUi(rawReply);
    const plan = extractPlanLines(clean);
    const hasKanban = ui && ui.kanban && Array.isArray(ui.kanban.columns) && ui.kanban.columns.length > 0;
    const hasSliders = ui && Array.isArray(ui.sliders) && ui.sliders.length > 0;
    if (!plan.length && !hasKanban && !hasSliders) {
      shell.classList.add("live-sheet--empty");
      clearPanels();
      return;
    }
    shell.classList.remove("live-sheet--empty");
    clearPanels();
    renderPlan(plan);
    if (hasKanban) renderKanban(ui);
    if (hasSliders) renderSliders(ui);
    const tab = document.getElementById("liveSheetTab");
    if (tab) {
      const bits = [];
      if (plan.length) bits.push(plan.filter((x) => x.kind === "num").length + " pasos");
      if (hasKanban) bits.push("kanban");
      if (hasSliders) bits.push("sliders");
      tab.textContent = "Plan en vivo · " + bits.join(" · ");
    }
    setExpanded(false);
    if (typeof deps.onAfterRender === "function") deps.onAfterRender(clean, assistantWrapEl);
  }

  function reset() {
    const shell = getShell();
    if (shell) {
      shell.classList.add("live-sheet--empty");
      clearPanels();
      const tab = document.getElementById("liveSheetTab");
      if (tab) tab.textContent = "Plan en vivo";
      setExpanded(false);
    }
    kanbanState = null;
  }

  function init(d) {
    deps = Object.assign({}, deps, d);
    const shell = getShell();
    const tab = document.getElementById("liveSheetTab");
    if (tab && shell) {
      tab.addEventListener("click", () => {
        const on = !shell.classList.contains("live-sheet--expanded");
        setExpanded(on);
      });
    }
    shell?.classList.add("live-sheet--empty");
  }

  global.LiveSheet = {
    init: init,
    reset: reset,
    strip: stripHelpdeskUi,
    parse: parseHelpdeskUi,
    afterAssistantReply: afterAssistantReply,
    setExpanded: setExpanded,
  };
})(typeof window !== "undefined" ? window : globalThis);
