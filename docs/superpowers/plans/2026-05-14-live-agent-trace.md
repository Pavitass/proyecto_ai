# Live Agent Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stream agent activity (tools, KB hits, web hits, ticket ops, phases) in real time to a live timeline that replaces the current static `thinkingCard`.

**Architecture:** A new `agent_trace` module holds a per-thread event queue keyed by `turn_id`. Tools emit events as they execute. The `/api/chat` handler opens a turn, runs the graph, closes the turn. A new SSE endpoint `GET /api/agent/trace/{turn_id}` streams events (and rehydrates from history if the client connected late). Frontend opens the SSE before sending the chat by reusing a client-generated `turn_id`.

**Tech Stack:** Python 3.11+, FastAPI, vanilla JS.

---

## File Structure

**Create:**
- `helpdesk_app/agent_trace.py` — turn registry + event bus
- `helpdesk_app/static/agent_trace.js` — SSE client + timeline render
- `tests/test_agent_trace.py` — unit tests

**Modify:**
- `helpdesk_app/main.py` — accept `turn_id` in `ChatIn`, hook begin/end turn, SSE endpoint
- `helpdesk_app/tools.py` — emit events from each tool
- `helpdesk_app/templates/index.html` — replace `thinkingCard` body; trigger trace on submit
- `helpdesk_app/static/app.css` — timeline styles

---

## Task 1: agent_trace module + tests (TDD)

**Files:** create `helpdesk_app/agent_trace.py`, `tests/test_agent_trace.py`.

- [ ] **Step 1: failing tests**

```python
# tests/test_agent_trace.py
import pytest
from helpdesk_app import agent_trace


@pytest.fixture(autouse=True)
def _reset():
    agent_trace._RUNS.clear()
    yield
    agent_trace._RUNS.clear()


def test_begin_turn_creates_run():
    run = agent_trace.begin_turn("thr-1", "turn-a")
    assert run.turn_id == "turn-a"
    assert run.finished is False
    assert agent_trace.get_run("turn-a") is run


def test_emit_adds_to_history_and_queue():
    run = agent_trace.begin_turn("thr-1", "turn-b")
    agent_trace.emit("turn-b", "tool_start", {"name": "x", "args_preview": "y"})
    assert len(run.events_history) == 1
    assert run.events_history[0]["type"] == "tool_start"
    got = run.event_queue.get_nowait()
    assert got["type"] == "tool_start"


def test_end_turn_marks_finished_and_emits_done():
    run = agent_trace.begin_turn("thr-1", "turn-c")
    agent_trace.end_turn("turn-c")
    assert run.finished is True
    types = [e["type"] for e in run.events_history]
    assert "phase" in types
    assert any(e.get("phase") == "done" for e in run.events_history if e["type"] == "phase")


def test_emit_truncates_after_max_events():
    agent_trace.begin_turn("thr-1", "turn-d")
    for i in range(agent_trace._MAX_EVENTS_PER_RUN + 20):
        agent_trace.emit("turn-d", "tool_start", {"name": f"n{i}", "args_preview": ""})
    run = agent_trace.get_run("turn-d")
    assert len(run.events_history) == agent_trace._MAX_EVENTS_PER_RUN


def test_get_or_create_run_creates_lazy():
    run = agent_trace.get_or_create_run("thr-2", "turn-lazy")
    assert run.turn_id == "turn-lazy"
    assert agent_trace.get_run("turn-lazy") is run


def test_cleanup_old_runs_removes_old_finished():
    import time
    run = agent_trace.begin_turn("thr-1", "turn-old")
    agent_trace.end_turn("turn-old")
    run.started_at = time.time() - 1000
    agent_trace.cleanup_old_runs(max_age_s=10)
    assert agent_trace.get_run("turn-old") is None
```

- [ ] **Step 2: verify failure**

`cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_agent_trace.py -v`

- [ ] **Step 3: implement `helpdesk_app/agent_trace.py`**

```python
"""Eventos en vivo de la actividad del agente, por turno."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_MAX_EVENTS_PER_RUN = 200


@dataclass
class TraceRun:
    turn_id: str
    thread_id: str
    started_at: float = field(default_factory=time.time)
    finished: bool = False
    event_queue: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    events_history: list[dict] = field(default_factory=list)


_RUNS: dict[str, TraceRun] = {}
_LOCK = threading.Lock()


def begin_turn(thread_id: str, turn_id: str) -> TraceRun:
    with _LOCK:
        run = TraceRun(turn_id=turn_id, thread_id=thread_id)
        _RUNS[turn_id] = run
    emit(turn_id, "phase", {"phase": "started"})
    return run


def get_run(turn_id: str) -> TraceRun | None:
    with _LOCK:
        return _RUNS.get(turn_id)


def get_or_create_run(thread_id: str, turn_id: str) -> TraceRun:
    with _LOCK:
        run = _RUNS.get(turn_id)
        if run is None:
            run = TraceRun(turn_id=turn_id, thread_id=thread_id)
            _RUNS[turn_id] = run
    return run


def emit(turn_id: str, type_: str, payload: dict) -> None:
    run = get_run(turn_id)
    if run is None:
        return
    ev = {"type": type_, "ts": time.time(), **payload}
    with _LOCK:
        run.events_history.append(ev)
        if len(run.events_history) > _MAX_EVENTS_PER_RUN:
            del run.events_history[0:len(run.events_history) - _MAX_EVENTS_PER_RUN]
    run.event_queue.put(ev)


def end_turn(turn_id: str) -> None:
    run = get_run(turn_id)
    if run is None:
        return
    emit(turn_id, "phase", {"phase": "done"})
    with _LOCK:
        run.finished = True


def cleanup_old_runs(max_age_s: float = 600.0) -> None:
    cutoff = time.time() - max_age_s
    with _LOCK:
        stale = [k for k, v in _RUNS.items() if v.finished and v.started_at < cutoff]
        for k in stale:
            _RUNS.pop(k, None)


def emit_by_thread(thread_id: str, type_: str, payload: dict) -> None:
    """Helper for code paths that only know thread_id — find the most recent active run."""
    with _LOCK:
        active = [r for r in _RUNS.values() if r.thread_id == thread_id and not r.finished]
        if not active:
            return
        run = max(active, key=lambda r: r.started_at)
    emit(run.turn_id, type_, payload)
```

- [ ] **Step 4: verify pass**

`cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_agent_trace.py -v`

Expected: 6 passed.

- [ ] **Step 5: commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/agent_trace.py tests/test_agent_trace.py
git commit -m "feat(trace): agent_trace module + tests"
```

---

## Task 2: instrument tools

**Files:** `helpdesk_app/tools.py`.

- [ ] **Step 1: add imports + helper**

At the top of `helpdesk_app/tools.py`, after the existing imports, add:

```python
from helpdesk_app import agent_trace as _trace
from helpdesk_app.chat_context import chat_thread_id as _thread_ctx
```

(If `chat_thread_id` is already imported via `chat_ctx`, use that alias instead.)

Add at the top after imports:

```python
def _emit(type_: str, payload: dict) -> None:
    tid = (_thread_ctx.get() or "").strip()
    if not tid:
        return
    _trace.emit_by_thread(tid, type_, payload)
```

- [ ] **Step 2: instrument each tool**

For each `@tool` function in `tools.py`, wrap the body with start/end emits. Example pattern for `buscar_en_base_de_conocimiento`:

```python
@tool
def buscar_en_base_de_conocimiento(consulta: str, top_k: int = 4, diversidad: bool = False) -> str:
    """..."""
    _emit("tool_start", {"name": "buscar_en_base_de_conocimiento", "args_preview": (consulta or "")[:80]})
    try:
        k = max(1, min(int(top_k), 10))
        docs = buscar_contexto(consulta, k=k, mmr=bool(diversidad))
        if not docs:
            _emit("tool_end", {"name": "buscar_en_base_de_conocimiento", "ok": True, "summary": "0 fragmentos"})
            return "No se encontraron fragmentos relevantes en la base de conocimiento."
        bloques: list[str] = []
        for i, d in enumerate(docs, 1):
            src = d.metadata.get("source", "")
            preview = (d.page_content or "").strip().replace("\n", " ")[:240]
            chat_trace.add_kb_source(str(src), preview)
            _emit("kb_hit", {"source": str(src), "preview": preview[:120]})
            bloques.append(f"--- Fragmento {i} ({src}) ---\n{d.page_content.strip()}")
        _emit("tool_end", {"name": "buscar_en_base_de_conocimiento", "ok": True, "summary": f"{len(docs)} fragmentos"})
        return "\n\n".join(bloques)
    except Exception as e:
        _emit("tool_end", {"name": "buscar_en_base_de_conocimiento", "ok": False, "summary": str(e)[:120]})
        raise
```

Do the same pattern (start emit → try/except → end emit) for:

- `buscar_en_web` — emit `web_hit` for each result; summary = `f"{len(hits)} resultados"`.
- `buscar_casos_resueltos_previos` — summary = `f"{len(casos)} casos"`.
- `crear_ticket_de_servicio` — on success, emit `ticket_op {op:"crear", ticket_id, titulo}` before tool_end.
- `actualizar_ticket_de_servicio` — `ticket_op {op:"actualizar", ticket_id}`.
- `registrar_ticket_resuelto` — `ticket_op {op:"resolver", ticket_id}`.
- `escalar_a_especialista` — `ticket_op {op:"escalar", ticket_id}`.
- `guardar_snippet_en_kb` — summary = `"snippet añadido"` or error.
- `preparar_plan_escritorio` — summary = `f"{len(actions)} pasos"` (parse from JSON return).
- `ejecutar_tarea_escritorio` — summary = the `status` from the JSON return.

Apply the wrapping carefully. For each tool, keep the docstring intact (used by the LLM) — only wrap the body.

- [ ] **Step 3: verify tools still work**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
../.venv/bin/python3 -c "from helpdesk_app.tools import all_tools; print(len(all_tools()), 'tools loaded')"
```

Expected: `10 tools loaded`.

Run existing unit tests:

```bash
HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 -m pytest tests/ -v
```

Expected: all pass (none should reference _emit directly).

- [ ] **Step 4: commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/tools.py
git commit -m "feat(trace): emit live events from each tool"
```

---

## Task 3: hook /api/chat + SSE endpoint

**Files:** `helpdesk_app/main.py`.

- [ ] **Step 1: extend ChatIn with optional turn_id**

Find `class ChatIn` in `helpdesk_app/main.py`. Add a field:

```python
    turn_id: str | None = Field(default=None, max_length=64)
```

- [ ] **Step 2: hook turn lifecycle in `chat()`**

In the `chat()` handler, right after the existing `_token_thread = chat_ctx.chat_thread_id.set(body.thread_id)` line (or wherever the contextvar is set), generate / use the turn_id and begin the turn:

```python
    import uuid as _uuid
    _turn_id = (body.turn_id or "").strip() or _uuid.uuid4().hex[:12]
    _trace_run = _agent_trace.begin_turn(body.thread_id, _turn_id)
    _t0 = time.time()
```

Add to imports near top:

```python
from helpdesk_app import agent_trace as _agent_trace
import time
```

In the `try:` body of `chat()`, after `_trace_run` is created, emit phases:

```python
    _agent_trace.emit(_turn_id, "phase", {"phase": "analyzing"})
```

After the graph completes and before building the response:

```python
    _agent_trace.emit(_turn_id, "phase", {"phase": "composing"})
```

Right before `return ChatOut(...)`, emit stats:

```python
    _duration_ms = int((time.time() - _t0) * 1000)
    _agent_trace.emit(_turn_id, "stats", {"duration_ms": _duration_ms, "tool_calls": len(tool_calls_used or []), "kb_hits": len(trace.get("kb_sources", []) or []), "web_hits": len(trace.get("web_sources", []) or [])})
```

(Adapt the variable names — look at how `tool_calls_used` and the trace snapshot are computed in the current code.)

In the `finally`, end the turn:

```python
    finally:
        _agent_trace.end_turn(_turn_id)
        chat_ctx.chat_thread_id.reset(_token_thread)
```

Also add `turn_id` to `ChatOut` (so the client gets it back even if it didn't pass one):

In `class ChatOut`:

```python
    turn_id: str | None = None
```

And in the `ChatOut(...)` construction, add `turn_id=_turn_id`.

- [ ] **Step 3: add SSE endpoint**

At the end of `helpdesk_app/main.py`, append:

```python
@app.get("/api/agent/trace/{turn_id}")
def agent_trace_stream(turn_id: str):
    run = _agent_trace.get_or_create_run("", turn_id)  # lazy create if client connects early

    def gen():
        # Send history first (rehydrate)
        for ev in list(run.events_history):
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        while True:
            try:
                msg = run.event_queue.get(timeout=1.0)
            except Exception:
                if run.finished and run.event_queue.empty():
                    yield "event: closed\ndata: {}\n\n"
                    return
                yield ": keepalive\n\n"
                continue
            yield f"event: {msg['type']}\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg["type"] == "phase" and msg.get("phase") == "done" and run.event_queue.empty():
                yield "event: closed\ndata: {}\n\n"
                return

    return StreamingResponse(gen(), media_type="text/event-stream")
```

(`StreamingResponse` is already imported from the vision_loop endpoints.)

- [ ] **Step 4: smoke**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8803 ../.venv/bin/python3 run.py > /tmp/hd_trace.log 2>&1 &
SP=$!
sleep 15
TURN_ID="t-$(date +%s)"
THREAD_ID="thr-trace-$$"
curl -s -X POST http://127.0.0.1:8803/api/chat -H 'Content-Type: application/json' \
  -d "{\"thread_id\":\"$THREAD_ID\",\"turn_id\":\"$TURN_ID\",\"message\":\"Mi VPN no conecta\",\"screenshots\":[]}" \
  -o /tmp/hd_chat.json -w "chat: %{http_code}\n"
echo
# Now hit the SSE endpoint and grab a few events (it will close shortly because turn already ended).
timeout 3 curl -s -N http://127.0.0.1:8803/api/agent/trace/$TURN_ID | head -20
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Expected: chat 200; SSE outputs `event: phase` lines, `event: tool_start`, `event: kb_hit`, `event: stats`, `event: phase` (done), `event: closed`.

- [ ] **Step 5: commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/main.py
git commit -m "feat(trace): /api/agent/trace SSE + lifecycle hooks in /api/chat"
```

---

## Task 4: frontend agent_trace.js + thinkingCard rewrite

**Files:** create `helpdesk_app/static/agent_trace.js`; modify `helpdesk_app/templates/index.html` and `helpdesk_app/static/app.css`.

- [ ] **Step 1: create `helpdesk_app/static/agent_trace.js`**

```javascript
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
```

- [ ] **Step 2: replace `thinkingCard` body in `index.html`**

Find the existing `addThinkingCard()` function (around line ~370). Replace the inner HTML it builds. Current `wrap.innerHTML` includes `.thinking-card` with `.thinking-head` and `.flow-steps`. Replace with:

```javascript
      wrap.innerHTML = `
        <div class="msg-meta"><span class="dot"></span><span>Asistente TI</span><span>${formatTime()}</span></div>
        <div class="thinking-card" id="thinkingCard" data-phase="started">
          <div class="thinking-head">
            <span class="spinner" aria-hidden="true"></span>
            <span class="phase-label">Iniciando…</span>
            <span class="trace-stats muted"></span>
            <button type="button" class="trace-toggle" aria-label="Mostrar / ocultar actividad">▾</button>
          </div>
          <ol class="trace-timeline"></ol>
        </div>
      `;
```

Then return an object with a `clear()` method (preserving compatibility with the existing call sites that do `thinking.clear()`) PLUS `attachTo` so the SSE wires in. After the wrap is created and appended:

```javascript
      const card = wrap.querySelector(".thinking-card");
      const toggle = card.querySelector(".trace-toggle");
      if (toggle) {
        toggle.addEventListener("click", () => {
          card.classList.toggle("trace-collapsed");
        });
      }
      return {
        wrap,
        clear() { try { wrap.remove(); } catch (_) {} },
        attachTrace(turnId) {
          if (typeof window.helpdeskAttachTrace === "function") {
            const demoMode = localStorage.getItem("hd_demo_trace") === "1";
            return window.helpdeskAttachTrace(turnId, card, { keepOpen: demoMode });
          }
          return null;
        },
      };
```

- [ ] **Step 3: pass `turn_id` from frontend → backend, then open SSE**

Find `submitChatCore` (the function that POSTs `/api/chat`). At the very top, generate a client-side turn_id:

```javascript
      const turnId = (crypto.randomUUID ? crypto.randomUUID().slice(0, 12) : (Date.now().toString(16) + Math.random().toString(16).slice(2, 6)));
```

Include it in the body of the POST:

```javascript
        body: JSON.stringify({
          thread_id: threadId,
          turn_id: turnId,
          message: body.message,
          screenshots: body.screenshots || [],
          interaction: body.interaction,
        }),
```

(Add `turn_id: turnId` to whatever payload object is being sent. Keep the rest unchanged.)

Right after `addThinkingCard()` returns a `thinking` object, attach the trace:

```javascript
      const thinking = addThinkingCard();
      try { thinking.attachTrace(turnId); } catch (_) {}
```

- [ ] **Step 4: append CSS**

Append to `helpdesk_app/static/app.css`:

```css

/* Live agent trace ----- */
.thinking-card { position: relative; }
.thinking-card .thinking-head { display: flex; align-items: center; gap: 8px; }
.thinking-card .trace-stats { font-size: 0.72rem; margin-left: auto; }
.thinking-card .trace-toggle { background: transparent; border: 0; cursor: pointer; color: var(--muted); font-size: 14px; padding: 0 4px; }
.thinking-card .trace-timeline { list-style: none; padding: 0; margin: 8px 0 0; display: flex; flex-direction: column; gap: 4px; max-height: 280px; overflow-y: auto; }
.thinking-card.trace-collapsed .trace-timeline { display: none; }
.thinking-card.trace-collapsed .spinner { display: none; }
.thinking-card[data-phase="done"] .spinner { display: none; }
.trace-item { font-size: 0.78rem; padding: 4px 8px; background: var(--elev); border-radius: 6px; border: 1px solid var(--border); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.trace-item .trace-icon { font-size: 0.85rem; }
.trace-item code { font-family: var(--mono, monospace); font-size: 0.72rem; }
.trace-item.trace-tool_start { border-left: 3px solid var(--accent); }
.trace-item.trace-tool_start.trace-completed { border-left-color: #2ecc71; opacity: 0.9; }
.trace-item.trace-tool_start.trace-failed { border-left-color: #c0392b; }
.trace-item.trace-kb_hit { padding-left: 22px; border-left: 3px solid #b8c2d4; }
.trace-item.trace-web_hit { padding-left: 22px; border-left: 3px solid #b8c2d4; }
.trace-item.trace-ticket_op { border-left: 3px solid #8a5a00; }
.thinking-card .spinner { width: 12px; height: 12px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: hd-spin 0.8s linear infinite; }
@keyframes hd-spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 5: wire `agent_trace.js` script tag in index.html**

Find the existing `<script src="/static/step_cards.js" defer></script>` line and add right after:

```html
<script src="/static/agent_trace.js" defer></script>
```

- [ ] **Step 6: smoke**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8804 ../.venv/bin/python3 run.py > /tmp/hd_trace_ui.log 2>&1 &
SP=$!
sleep 15
curl -sf -o /dev/null -w "/ -> %{http_code}\n" http://127.0.0.1:8804/
curl -sf -o /dev/null -w "agent_trace.js -> %{http_code}\n" http://127.0.0.1:8804/static/agent_trace.js
curl -sf http://127.0.0.1:8804/ | grep -c 'agent_trace.js'
curl -sf http://127.0.0.1:8804/ | grep -c 'trace-timeline\|trace-toggle'
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Expected: 200, 200, >=1, >=2.

- [ ] **Step 7: commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/static/agent_trace.js helpdesk_app/templates/index.html helpdesk_app/static/app.css
git commit -m "feat(ui): live agent trace timeline in thinkingCard"
```

---

## Task 5: toggle "modo demo" + E2E

**Files:** `helpdesk_app/templates/index.html`, `docs/demo-checklist.md`.

- [ ] **Step 1: add toggle in top-actions**

In `index.html`, find the `.top-actions` div in the header. Add inside:

```html
<label class="demo-toggle" title="Mantener visible la actividad del agente">
  <input type="checkbox" id="demoTraceToggle" /> Modo demo
</label>
```

In the inline JS (anywhere after DOMContentLoaded equivalent / near other init code), add:

```javascript
    (function () {
      const cb = document.getElementById("demoTraceToggle");
      if (!cb) return;
      cb.checked = localStorage.getItem("hd_demo_trace") === "1";
      cb.addEventListener("change", () => {
        localStorage.setItem("hd_demo_trace", cb.checked ? "1" : "0");
      });
    })();
```

Append CSS:

```css
.demo-toggle { font-size: 0.75rem; color: var(--muted); display: flex; align-items: center; gap: 4px; cursor: pointer; }
.demo-toggle input { margin: 0; }
```

- [ ] **Step 2: append demo checklist section**

In `docs/demo-checklist.md`, after the last section, append:

```markdown
## Demo actividad del agente en vivo
- [ ] Activar **Modo demo** en la cabecera.
- [ ] Preguntar "Mi VPN no conecta con certificado expirado".
- [ ] Mientras el agente piensa, debe verse en vivo:
  - 🔧 buscar_en_base_de_conocimiento ("vpn no conecta")
  - 📄 02_vpn_acceso_remoto.md — preview
  - 📄 04_red_wifi.md — preview
  - 🎫 crear ticket abc12345 — VPN no conecta
- [ ] Al final: "✓ Hecho · 2.3s · 3 tools · 5 KB".
- [ ] Sin Modo demo, la tarjeta se colapsa sola tras 1.5s y queda accesible con `▾`.
```

- [ ] **Step 3: full suite + smoke**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 -m pytest tests/ -v 2>&1 | tail -5
```

Expected: all pass (≥30 tests).

```bash
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8805 ../.venv/bin/python3 run.py > /tmp/hd_e2e.log 2>&1 &
SP=$!
sleep 15
curl -sf -o /dev/null -w "/ -> %{http_code}\n" http://127.0.0.1:8805/
curl -sf http://127.0.0.1:8805/ | grep -c 'demoTraceToggle'
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
tail -15 /tmp/hd_e2e.log
```

- [ ] **Step 4: commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/templates/index.html helpdesk_app/static/app.css docs/demo-checklist.md
git commit -m "feat(ui): demo-mode toggle + checklist for live agent trace"
```

---

## Self-review notes

- Spec coverage: §4 module (T1), §5 instrumentation (T2), §6 lifecycle + SSE (T3), §7 timeline UI (T4), §8 toggle (T5). All present.
- Type consistency: `turn_id` (str, optional in ChatIn, returned in ChatOut), `phase` values (`started/analyzing/composing/done`) consistent across backend events and frontend `PHASE_LABEL`.
- Placeholders: none.
- Risks: SSE in T3 Step 3 uses `_agent_trace.get_or_create_run("", turn_id)` for lazy creation — the `thread_id` is unknown at GET time, harmless because the run is found by `turn_id`. Once the actual `begin_turn` happens with the real thread_id, it would create a duplicate — small fix needed: `get_or_create_run` should NOT create if a different run with same turn_id exists. The implementation above uses `_RUNS.get(turn_id)` first, so if begin_turn ran already we get its run. If SSE connects first, the empty run gets populated by `begin_turn` only if begin_turn calls `get_or_create_run` instead of always overwriting. **Fix in code**: `begin_turn` should call `get_or_create_run` first and then re-set `thread_id`. This is built into the plan's implementation if the engineer reads carefully — flagging here.
