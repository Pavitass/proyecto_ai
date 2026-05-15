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

  function renderSurvey(data) {
    if (!data || !data.fields || !data.fields.length) return null;
    const wrap = el("div", "widget-survey");
    if (data.prompt) wrap.appendChild(el("div", "widget-prompt", data.prompt));
    const form = el("form", "widget-survey-form");
    const inputs = [];
    data.fields.slice(0, 8).forEach((f) => {
      const row = el("div", "widget-survey-row");
      const lbl = el("label", "widget-survey-label", (f.label || f.id || "?") + (f.required ? " *" : ""));
      row.appendChild(lbl);
      const fid = "f_" + (f.id || Math.random().toString(36).slice(2, 8));
      lbl.htmlFor = fid;
      if (f.type === "choice" && Array.isArray(f.options) && f.options.length) {
        const group = el("div", "widget-survey-choices");
        f.options.slice(0, 8).forEach((opt, i) => {
          const optId = fid + "_" + i;
          const label = el("label", "widget-survey-choice");
          const radio = el("input");
          radio.type = "radio"; radio.name = fid; radio.value = (opt.label || opt) ; radio.id = optId;
          const span = el("span", null, opt.label || opt);
          label.appendChild(radio); label.appendChild(span);
          group.appendChild(label);
        });
        row.appendChild(group);
        inputs.push({ id: f.id, type: "choice", get: () => {
          const checked = group.querySelector("input:checked");
          return checked ? checked.value : "";
        }});
      } else if (f.type === "textarea") {
        const ta = el("textarea");
        ta.id = fid; ta.rows = 2;
        if (f.placeholder) ta.placeholder = f.placeholder;
        row.appendChild(ta);
        inputs.push({ id: f.id, type: "text", get: () => ta.value.trim() });
      } else {
        const inp = el("input");
        inp.type = "text"; inp.id = fid;
        if (f.placeholder) inp.placeholder = f.placeholder;
        row.appendChild(inp);
        inputs.push({ id: f.id, type: "text", get: () => inp.value.trim() });
      }
      form.appendChild(row);
    });
    const submit = el("button", "widget-survey-submit", data.submit_label || "Enviar respuestas");
    submit.type = "submit";
    form.appendChild(submit);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const lines = [`[survey ${data.id || "diag"}]`];
      let any = false;
      inputs.forEach((inp) => {
        const v = inp.get();
        if (v) { lines.push(`- ${inp.id}: ${v}`); any = true; }
      });
      if (!any) return;
      submit.disabled = true;
      submit.textContent = "Enviado";
      const composed = lines.join("\n");
      if (typeof window.helpdeskSubmitChat === "function") {
        window.helpdeskSubmitChat(composed);
      }
    });
    wrap.appendChild(form);
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
    if (data.survey) {
      const n = renderSurvey(data.survey);
      if (n) container.appendChild(n);
    }
  }

  window.helpdeskRenderWidgets = renderWidgets;

  document.addEventListener("helpdesk:ui-block", (ev) => {
    const { data, container } = ev.detail || {};
    if (data && container) renderWidgets(data, container);
  });
})();
