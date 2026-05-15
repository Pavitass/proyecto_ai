/* Render de widgets adicionales emitidos por la IA dentro del bloque `helpdesk-ui`:
 *  - choice (opción única radio-style) → al pulsar, envía mensaje al chat
 *  - severity (slider 1..5 con etiquetas) → silencioso, guarda como nota de paso virtual
 */
(function () {
  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function renderChoice(data) {
    if (!data || !data.options || !data.options.length) return null;
    const wrap = el("div", "widget-choice");
    wrap.appendChild(el("div", "widget-prompt", data.prompt || "Elige una opción"));
    const list = el("div", "widget-choice-list");
    data.options.slice(0, 5).forEach((opt) => {
      const btn = el("button", "widget-choice-opt", opt.label || opt.id || "?");
      btn.type = "button";
      btn.addEventListener("click", () => {
        const composed = `[choice ${data.id || "opt"}] "${opt.label || opt.id}"`;
        if (typeof window.helpdeskSubmitChat === "function") {
          window.helpdeskSubmitChat(composed);
        }
      });
      list.appendChild(btn);
    });
    wrap.appendChild(list);
    return wrap;
  }

  function renderSeverity(data) {
    if (!data) return null;
    const labels = (data.labels && data.labels.length === 5) ? data.labels : [
      "Solo molesto", "Lento pero funciono", "A medias", "Sin trabajar", "Toda mi tarea bloqueada",
    ];
    const wrap = el("div", "widget-severity");
    wrap.appendChild(el("div", "widget-prompt", data.prompt || "¿Cuánto te bloquea esto?"));
    const slider = el("input");
    slider.type = "range"; slider.min = "1"; slider.max = "5"; slider.value = "3";
    const label = el("div", "widget-severity-label", `${slider.value}/5 — ${labels[2]}`);
    slider.addEventListener("input", () => {
      const v = Number(slider.value);
      label.textContent = `${v}/5 — ${labels[v - 1]}`;
    });
    slider.addEventListener("change", () => {
      const v = Number(slider.value);
      const tid = (window.__HELPDESK_THREAD_ID__ || "");
      if (!tid) return;
      const mid = "_severity_" + (data.id || "imp");
      fetch("/api/steps/register", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: tid, message_id: mid, steps: [{ index: 0, text: data.prompt || "severity" }] }),
      }).then(() => fetch("/api/steps/update", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: tid, message_id: mid,
          index: 0, status: "stuck", note: `gravedad ${v}/5 — ${labels[v - 1]}`,
        }),
      })).catch(() => {});
    });
    wrap.appendChild(slider);
    wrap.appendChild(label);
    return wrap;
  }

  function renderWidgets(data, container) {
    if (!data || !container) return;
    if (data.choice) {
      const n = renderChoice(data.choice);
      if (n) container.appendChild(n);
    }
    if (data.severity) {
      const n = renderSeverity(data.severity);
      if (n) container.appendChild(n);
    }
  }

  window.helpdeskRenderWidgets = renderWidgets;

  document.addEventListener("helpdesk:ui-block", (ev) => {
    const { data, container } = ev.detail || {};
    if (data && container) renderWidgets(data, container);
  });
})();
