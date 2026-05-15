/* Step-cards: detecta listas de "Plan de acción" en burbujas del asistente y las
 * reemplaza por tarjetas interactivas. Comunica con /api/steps/* sin pasar por el LLM. */
(function () {
  const ICON = { pending: "◯", current: "▶", done: "✓", stuck: "✕" };

  function threadId() {
    return (typeof window.threadId === "string" && window.threadId) ||
      (window.__HELPDESK_THREAD_ID__ || "");
  }

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function extractSteps(bubble) {
    const md = bubble.querySelector(".md-content") || bubble;
    const headings = Array.from(md.querySelectorAll("h2, h3"));
    const target = headings.find((h) =>
      (h.textContent || "").toLowerCase().includes("plan de acción")
    );
    let ol = null;
    if (target) {
      let n = target.nextElementSibling;
      while (n && !ol) {
        if (n.tagName === "OL") ol = n;
        n = n.nextElementSibling;
      }
    }
    if (!ol) ol = md.querySelector("ol");
    if (!ol || ol.children.length < 2) return null;
    const steps = Array.from(ol.children).map((li, i) => {
      const clone = li.cloneNode(true);
      clone.querySelectorAll("input").forEach((x) => x.remove());
      return { index: i, text: clone.textContent.replace(/\s+/g, " ").trim() };
    });
    return { ol, steps };
  }

  function buildCard(step) {
    const div = document.createElement("div");
    div.className = "step-card";
    div.dataset.index = String(step.index);
    div.dataset.status = "pending";
    div.innerHTML = `
      <div class="step-head">
        <span class="step-num">${step.index + 1}</span>
        <span class="step-status-icon">${ICON.pending}</span>
        <span class="step-text"></span>
      </div>
      <div class="step-actions">
        <button type="button" class="btn-done">✓ Hecho</button>
        <button type="button" class="btn-stuck">✕ Atascado</button>
        <button type="button" class="btn-shot">📷 Captura</button>
      </div>
      <div class="step-stuck-form" hidden>
        <textarea placeholder="¿Qué pasa en este paso? (qué ves, qué falla)"></textarea>
        <div class="step-stuck-actions">
          <button type="button" class="btn-stuck-shot">📷 Adjuntar captura</button>
          <button type="button" class="btn-stuck-send">Enviar al agente</button>
          <button type="button" class="btn-stuck-cancel">Cancelar</button>
        </div>
      </div>
    `;
    div.querySelector(".step-text").textContent = step.text;
    return div;
  }

  function setStatus(card, status) {
    card.dataset.status = status;
    const icon = card.querySelector(".step-status-icon");
    icon.textContent = ICON[status] || ICON.pending;
  }

  function markCurrent(container) {
    const cards = Array.from(container.querySelectorAll(".step-card"));
    cards.forEach((c) => { if (c.dataset.status === "current") setStatus(c, "pending"); });
    const next = cards.find((c) => c.dataset.status === "pending");
    if (next) setStatus(next, "current");
  }

  function attachStepCardListeners(container, msgId) {
    const tid = threadId();
    container.querySelectorAll(".step-card").forEach((card) => {
      const idx = Number(card.dataset.index);
      const btnDone = card.querySelector(".btn-done");
      const btnStuck = card.querySelector(".btn-stuck");
      const btnShot = card.querySelector(".btn-shot");
      const form = card.querySelector(".step-stuck-form");
      const ta = form.querySelector("textarea");
      const btnStuckShot = form.querySelector(".btn-stuck-shot");
      const btnStuckSend = form.querySelector(".btn-stuck-send");
      const btnStuckCancel = form.querySelector(".btn-stuck-cancel");

      btnDone.addEventListener("click", async () => {
        const prev = card.dataset.status;
        const next = prev === "done" ? "pending" : "done";
        setStatus(card, next);
        try {
          await postJSON("/api/steps/update", {
            thread_id: tid, message_id: msgId, index: idx, status: next,
          });
          markCurrent(container);
        } catch (_) {
          setStatus(card, prev);
        }
      });

      btnStuck.addEventListener("click", () => {
        const willOpen = form.hasAttribute("hidden");
        if (willOpen) form.removeAttribute("hidden"); else form.setAttribute("hidden", "");
      });

      btnShot.addEventListener("click", () => {
        const msgEl = document.getElementById("msg");
        if (msgEl) {
          msgEl.value = `[Paso ${idx + 1}] `;
          msgEl.focus();
        }
        const shotBtn = document.getElementById("btnShotScreen");
        if (shotBtn) shotBtn.click();
      });

      btnStuckShot.addEventListener("click", () => {
        const shotBtn = document.getElementById("btnShotScreen");
        if (shotBtn) shotBtn.click();
      });

      btnStuckCancel.addEventListener("click", () => {
        form.setAttribute("hidden", "");
        ta.value = "";
      });

      btnStuckSend.addEventListener("click", async () => {
        const note = ta.value.trim();
        if (!note) { ta.focus(); return; }
        setStatus(card, "stuck");
        try {
          await postJSON("/api/steps/update", {
            thread_id: tid, message_id: msgId, index: idx, status: "stuck", note,
          });
        } catch (_) {}
        const stepText = (card.querySelector(".step-text") || {}).textContent || "";
        const composed = `[Paso ${idx + 1} atascado] "${stepText.slice(0, 200)}"\nLo que veo: ${note}`;
        form.setAttribute("hidden", "");
        if (typeof window.helpdeskSubmitChat === "function") {
          window.helpdeskSubmitChat(composed);
        } else {
          const msgEl = document.getElementById("msg");
          if (msgEl) { msgEl.value = composed; msgEl.focus(); }
        }
      });
    });
  }

  function enhanceAssistantBubble(bubble) {
    if (!bubble || bubble.dataset.stepCardsDone === "1") return;
    const extracted = extractSteps(bubble);
    if (!extracted) return;
    bubble.dataset.stepCardsDone = "1";
    const msgId = "msg-" + (crypto.randomUUID ? crypto.randomUUID().slice(0, 8) : Math.random().toString(16).slice(2, 10));
    const container = document.createElement("div");
    container.className = "step-cards";
    container.dataset.msgId = msgId;
    extracted.steps.forEach((s) => container.appendChild(buildCard(s)));
    const footer = document.createElement("div");
    footer.className = "step-cards-footer";
    footer.innerHTML = `<button type="button" class="btn-feedback">📨 Pedir comentario al agente</button>`;
    footer.querySelector(".btn-feedback").addEventListener("click", () => {
      const composed = "[Estado de pasos actualizado] revisa el progreso y dime el siguiente micro-paso si aplica.";
      if (typeof window.helpdeskSubmitChat === "function") window.helpdeskSubmitChat(composed);
    });

    extracted.ol.replaceWith(container);
    container.after(footer);
    markCurrent(container);

    const tid = threadId();
    if (tid) {
      postJSON("/api/steps/register", {
        thread_id: tid, message_id: msgId, steps: extracted.steps.map((s) => ({ index: s.index, text: s.text })),
      }).catch(() => {});
    }

    attachStepCardListeners(container, msgId);
  }

  window.helpdeskEnhanceSteps = enhanceAssistantBubble;
})();
