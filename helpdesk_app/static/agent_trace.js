/* Cliente SSE del trace en vivo del agente. */
(function () {
  const ICON_BY_TYPE = {
    tool_start: "🔧",
    tool_end: "✓",
    kb_hit: "📄",
    web_hit: "🌐",
    ticket_op: "🎫",
  };
  const PHASE_LABEL = {
    analyzing: "Analizando tu mensaje…",
    tool_calling: "Llamando herramientas…",
    composing: "Componiendo respuesta…",
    done: "Hecho",
    started: "Iniciando…",
  };

  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function render(timelineEl, event) {
    const li = el("li", "trace-item trace-" + event.type);
    switch (event.type) {
      case "tool_start":
        li.dataset.toolName = event.name || "";
        li.innerHTML = `<span class="trace-icon">${ICON_BY_TYPE.tool_start}</span> <code class="trace-tool">${event.name || "?"}</code> <span class="trace-args muted">${(event.args_preview || "").replace(/</g, "&lt;")}</span>`;
        break;
      case "tool_end": {
        // Mark the matching tool_start as completed
        const found = Array.from(timelineEl.querySelectorAll('.trace-tool_start[data-tool-name="' + (event.name || "") + '"]:not(.trace-completed)')).pop();
        if (found) {
          found.classList.add("trace-completed");
          if (!event.ok) found.classList.add("trace-failed");
          const sum = el("span", "trace-summary muted", " — " + (event.summary || ""));
          found.appendChild(sum);
          return; // do NOT append a new li
        }
        return;
      }
      case "kb_hit":
        li.innerHTML = `<span class="trace-icon">${ICON_BY_TYPE.kb_hit}</span> <code class="trace-source">${(event.source || "").replace(/</g, "&lt;")}</code> <span class="muted">— ${(event.preview || "").replace(/</g, "&lt;")}</span>`;
        break;
      case "web_hit":
        li.innerHTML = `<span class="trace-icon">${ICON_BY_TYPE.web_hit}</span> <a href="${(event.url || "#").replace(/"/g, "&quot;")}" target="_blank" rel="noopener">${(event.title || event.url || "").replace(/</g, "&lt;")}</a>`;
        break;
      case "ticket_op":
        li.innerHTML = `<span class="trace-icon">${ICON_BY_TYPE.ticket_op}</span> <strong>${event.op}</strong> ticket <code>${String(event.ticket_id || "").slice(0, 8)}</code> ${event.titulo ? "— " + String(event.titulo).replace(/</g, "&lt;") : ""}`;
        break;
      default:
        return;
    }
    timelineEl.appendChild(li);
  }

  function setPhase(headerEl, phase) {
    if (!headerEl) return;
    const label = headerEl.querySelector(".phase-label");
    if (label) label.textContent = PHASE_LABEL[phase] || phase;
    headerEl.dataset.phase = phase;
  }

  function setStats(headerEl, stats) {
    if (!headerEl) return;
    const s = headerEl.querySelector(".trace-stats");
    if (!s || !stats) return;
    const parts = [];
    if (stats.duration_ms != null) parts.push((stats.duration_ms / 1000).toFixed(1) + "s");
    if (stats.tool_calls != null) parts.push(stats.tool_calls + " tools");
    if (stats.kb_hits) parts.push(stats.kb_hits + " KB");
    if (stats.web_hits) parts.push(stats.web_hits + " web");
    s.textContent = parts.join(" · ");
  }

  function attachTrace(turnId, mountEl, opts) {
    opts = opts || {};
    const timeline = mountEl.querySelector(".trace-timeline");
    const header = mountEl.querySelector(".thinking-head");
    if (!timeline) return null;
    const es = new EventSource("/api/agent/trace/" + encodeURIComponent(turnId));
    ["tool_start", "tool_end", "kb_hit", "web_hit", "ticket_op"].forEach((kind) => {
      es.addEventListener(kind, (e) => {
        try { render(timeline, Object.assign({ type: kind }, JSON.parse(e.data))); } catch (_) {}
      });
    });
    es.addEventListener("phase", (e) => {
      try {
        const d = JSON.parse(e.data);
        setPhase(header, d.phase);
        if (d.phase === "done") {
          mountEl.dataset.finished = "1";
          if (!opts.keepOpen) {
            setTimeout(() => { mountEl.classList.add("trace-collapsed"); }, 1500);
          }
        }
      } catch (_) {}
    });
    es.addEventListener("stats", (e) => {
      try { setStats(header, JSON.parse(e.data)); } catch (_) {}
    });
    es.addEventListener("closed", () => { es.close(); });
    return es;
  }

  window.helpdeskAttachTrace = attachTrace;
})();
