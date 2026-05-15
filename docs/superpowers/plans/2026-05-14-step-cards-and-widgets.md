# Step-cards + Widgets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the slow per-checkbox LLM regeneration with instant step-cards, add an inline "stuck" form with context-aware LLM dispatch, and extend `helpdesk-ui` blocks with `choice` and `severity` widgets the LLM can generate.

**Architecture:** A pure-Python `step_state` module holds in-memory step status per thread. Three lightweight FastAPI endpoints (register / update / fetch) skip the LangGraph entirely. Frontend JS detects ordered lists in assistant responses, replaces them with interactive cards, and POSTs status changes directly. The chat handler prepends an `[Estado de pasos]` block to the latest user message so the LLM always sees current status. The existing `helpdesk-ui` JSON block parser is extended to recognize `choice` and `severity`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, vanilla JS (no framework — the chat is already vanilla), CSS in existing `app.css`.

---

## File Structure

**Create:**
- `helpdesk_app/step_state.py` — in-memory thread → message → steps store, thread-safe
- `helpdesk_app/static/step_cards.js` — detect lists, render cards, wire actions
- `helpdesk_app/static/widgets.js` — render `choice` and `severity` widgets
- `tests/test_step_state.py` — unit tests for the store

**Modify:**
- `helpdesk_app/main.py` — add `/api/steps/register`, `/api/steps/update`, `/api/steps/{thread_id}` endpoints; inject `[Estado de pasos]` into `/api/chat` user message
- `helpdesk_app/interactive_block.py` — keep `parse_helpdesk_ui_block` working; no schema change needed (JSON is opaque)
- `helpdesk_app/templates/index.html` — wire `step_cards.js` and `widgets.js`, hook into existing `addMessage` for assistant bubbles
- `helpdesk_app/static/app.css` — styles for `.step-card`, `.step-stuck-form`, `.widget-choice`, `.widget-severity`
- `helpdesk_app/graph.py` — system prompt mentions `choice` / `severity` and "respeta los pasos ya marcados como ✓"

---

## Task 1: step_state module + tests

**Files:**
- Create: `helpdesk_app/step_state.py`
- Test: `tests/test_step_state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_step_state.py`:

```python
import pytest
from helpdesk_app import step_state


@pytest.fixture(autouse=True)
def _reset():
    step_state.clear_all()
    yield
    step_state.clear_all()


def test_upsert_then_get():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "abrir spotlight"}, {"index": 1, "text": "escribir"}])
    got = step_state.get_steps("t1")
    assert got == {"m1": [{"index": 0, "text": "abrir spotlight", "status": "pending", "note": ""},
                          {"index": 1, "text": "escribir", "status": "pending", "note": ""}]}


def test_update_step_status():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "abrir spotlight"}])
    ok = step_state.update_step("t1", "m1", 0, "done")
    assert ok is True
    got = step_state.get_steps("t1")
    assert got["m1"][0]["status"] == "done"


def test_update_stuck_carries_note():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "x"}])
    ok = step_state.update_step("t1", "m1", 0, "stuck", note="no aparece el botón")
    assert ok is True
    assert step_state.get_steps("t1")["m1"][0] == {"index": 0, "text": "x", "status": "stuck", "note": "no aparece el botón"}


def test_update_unknown_thread_returns_false():
    assert step_state.update_step("nope", "m1", 0, "done") is False


def test_update_unknown_index_returns_false():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "x"}])
    assert step_state.update_step("t1", "m1", 5, "done") is False


def test_update_invalid_status_raises():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "x"}])
    with pytest.raises(ValueError):
        step_state.update_step("t1", "m1", 0, "wrong")


def test_upsert_replaces_existing_message():
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "old"}])
    step_state.update_step("t1", "m1", 0, "done")
    step_state.upsert_steps("t1", "m1", [{"index": 0, "text": "new"}])
    assert step_state.get_steps("t1")["m1"][0]["status"] == "pending"
    assert step_state.get_steps("t1")["m1"][0]["text"] == "new"


def test_render_status_block_empty():
    assert step_state.render_status_block("t1") == ""


def test_render_status_block_has_icons():
    step_state.upsert_steps("t1", "m1", [
        {"index": 0, "text": "abrir spotlight"},
        {"index": 1, "text": "escribir"},
        {"index": 2, "text": "enter"},
    ])
    step_state.update_step("t1", "m1", 0, "done")
    step_state.update_step("t1", "m1", 1, "stuck", note="no carga")
    out = step_state.render_status_block("t1")
    assert "[Estado de pasos]" in out
    assert "1✓" in out and "2✕" in out and "3◯" in out
    assert "no carga" in out
```

- [ ] **Step 2: Verify failure**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_step_state.py -v`
Expected: ImportError / module not found.

- [ ] **Step 3: Implement `helpdesk_app/step_state.py`**

```python
"""Estado en memoria de pasos por hilo (thread_id → message_id → [steps])."""
from __future__ import annotations

from threading import Lock
from typing import Literal

Status = Literal["pending", "done", "stuck"]
_ALLOWED_STATUS: frozenset[str] = frozenset({"pending", "done", "stuck"})

# {thread_id: {message_id: [{"index": int, "text": str, "status": Status, "note": str}, ...]}}
_STORE: dict[str, dict[str, list[dict]]] = {}
_LOCK = Lock()

_ICON = {"pending": "◯", "done": "✓", "stuck": "✕"}


def upsert_steps(thread_id: str, message_id: str, steps: list[dict]) -> None:
    """Replace the steps for (thread_id, message_id). Existing statuses for this message are dropped."""
    normalized: list[dict] = []
    for s in steps:
        normalized.append({
            "index": int(s["index"]),
            "text": str(s.get("text", ""))[:500],
            "status": "pending",
            "note": "",
        })
    with _LOCK:
        _STORE.setdefault(thread_id, {})[message_id] = normalized


def update_step(thread_id: str, message_id: str, index: int, status: str, note: str = "") -> bool:
    if status not in _ALLOWED_STATUS:
        raise ValueError(f"status inválido: {status}")
    with _LOCK:
        msgs = _STORE.get(thread_id)
        if not msgs:
            return False
        steps = msgs.get(message_id)
        if not steps:
            return False
        for s in steps:
            if s["index"] == index:
                s["status"] = status
                s["note"] = str(note or "")[:500]
                return True
        return False


def get_steps(thread_id: str) -> dict[str, list[dict]]:
    with _LOCK:
        msgs = _STORE.get(thread_id, {})
        return {k: [dict(s) for s in v] for k, v in msgs.items()}


def render_status_block(thread_id: str) -> str:
    """Compact one-message-per-line view used to brief the LLM on the next turn."""
    snapshot = get_steps(thread_id)
    if not snapshot:
        return ""
    lines = ["[Estado de pasos]"]
    for msg_id, steps in snapshot.items():
        if not steps:
            continue
        parts: list[str] = []
        stuck_notes: list[str] = []
        for s in steps:
            icon = _ICON.get(s["status"], "◯")
            parts.append(f"{s['index'] + 1}{icon}")
            if s["status"] == "stuck" and s["note"]:
                stuck_notes.append(f"paso {s['index'] + 1}: {s['note']}")
        line = f"  {msg_id}: " + ", ".join(parts)
        if stuck_notes:
            line += " — atascos: " + "; ".join(stuck_notes)
        lines.append(line)
    return "\n".join(lines)


def clear_thread(thread_id: str) -> None:
    with _LOCK:
        _STORE.pop(thread_id, None)


def clear_all() -> None:
    with _LOCK:
        _STORE.clear()
```

- [ ] **Step 4: Verify pass**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_step_state.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/step_state.py tests/test_step_state.py
git commit -m "feat(steps): in-memory step state store per thread"
```

---

## Task 2: FastAPI endpoints

**Files:**
- Modify: `helpdesk_app/main.py`

- [ ] **Step 1: Read main.py around the existing `/api/thread` and `/api/chat` endpoints** to identify where to append the new endpoints. Existing imports already include `HTTPException`, `BaseModel`, `Field` from pydantic, and `json`.

- [ ] **Step 2: Append the new endpoints**

At the end of `helpdesk_app/main.py` (after the vision_loop endpoints added in the previous feature), append:

```python
from helpdesk_app import step_state as _step_state


class _StepRegisterBody(BaseModel):
    thread_id: str = Field(..., min_length=4, max_length=128)
    message_id: str = Field(..., min_length=4, max_length=128)
    steps: list[dict] = Field(..., max_length=40)


class _StepUpdateBody(BaseModel):
    thread_id: str = Field(..., min_length=4, max_length=128)
    message_id: str = Field(..., min_length=4, max_length=128)
    index: int = Field(..., ge=0, le=200)
    status: str
    note: str = Field(default="", max_length=500)


@app.post("/api/steps/register")
def steps_register(body: _StepRegisterBody):
    _step_state.upsert_steps(body.thread_id, body.message_id, body.steps)
    return {"ok": True}


@app.post("/api/steps/update")
def steps_update(body: _StepUpdateBody):
    try:
        ok = _step_state.update_step(body.thread_id, body.message_id, body.index, body.status, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "thread/message/index no encontrado")
    return {"ok": True}


@app.get("/api/steps/{thread_id}")
def steps_get(thread_id: str):
    if len(thread_id) < 4 or len(thread_id) > 128:
        raise HTTPException(400, "thread_id inválido")
    return {"thread_id": thread_id, "messages": _step_state.get_steps(thread_id)}
```

- [ ] **Step 3: Inject `[Estado de pasos]` into the chat request**

Inside the existing `chat()` handler in `main.py` (around line 326+), locate where the `HumanMessage` for the user's input is constructed and added to the graph input. Just before that line, build the prefix:

```python
steps_block = _step_state.render_status_block(body.thread_id)
user_text = body.message
if steps_block:
    user_text = steps_block + "\n\n" + user_text
```

Then use `user_text` instead of `body.message` when constructing the `HumanMessage`. (The exact variable name to change depends on the existing code — read the function and adapt.)

- [ ] **Step 4: Smoke test endpoints**

Start server:

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8794 ../.venv/bin/python3 run.py &
SP=$!
sleep 6
```

```bash
curl -s -X POST http://127.0.0.1:8794/api/steps/register -H 'Content-Type: application/json' \
  -d '{"thread_id":"thr-abc","message_id":"msg-1","steps":[{"index":0,"text":"a"},{"index":1,"text":"b"}]}'
# expected: {"ok":true}

curl -s -X POST http://127.0.0.1:8794/api/steps/update -H 'Content-Type: application/json' \
  -d '{"thread_id":"thr-abc","message_id":"msg-1","index":0,"status":"done"}'
# expected: {"ok":true}

curl -s http://127.0.0.1:8794/api/steps/thr-abc
# expected: {"thread_id":"thr-abc","messages":{"msg-1":[{"index":0,"text":"a","status":"done","note":""},{"index":1,"text":"b","status":"pending","note":""}]}}

curl -i -X POST http://127.0.0.1:8794/api/steps/update -H 'Content-Type: application/json' \
  -d '{"thread_id":"thr-abc","message_id":"msg-1","index":0,"status":"BAD"}'
# expected: HTTP 400

kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

All four results must match expected.

- [ ] **Step 5: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/main.py
git commit -m "feat(steps): API endpoints + inject status block in /api/chat"
```

---

## Task 3: Frontend step_cards.js — detection + render

**Files:**
- Create: `helpdesk_app/static/step_cards.js`
- Modify: `helpdesk_app/templates/index.html`
- Modify: `helpdesk_app/static/app.css`

- [ ] **Step 1: Create `helpdesk_app/static/step_cards.js`**

```javascript
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
    // Find an <ol> preceded (anywhere prior) by a heading containing "plan de acción".
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
    if (!ol) ol = md.querySelector("ol"); // fallback: first <ol>
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
      let stuckShotAttached = false;

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
        if (shotBtn) {
          stuckShotAttached = true;
          shotBtn.click();
        }
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
```

- [ ] **Step 2: Wire the script in `helpdesk_app/templates/index.html`**

Find the line near the bottom that loads `automation_panel.js` (added in a previous feature). Above or below it, add:

```html
<script src="/static/step_cards.js" defer></script>
<script src="/static/widgets.js" defer></script>
```

(`widgets.js` will be created in Task 5; the 404 until then is harmless because the script is `defer`-loaded.)

Then find the `addMessage` function (search for `"function addMessage"`) and inside the block `if (isMarkdown)` (which already calls `enhanceInteractiveSteps(bubble)` and `wireAssistantTaskCheckboxes(bubble)` for assistant messages), add ONE more call for assistant messages, right after `wireAssistantTaskCheckboxes(bubble)`:

```javascript
if (role === "assistant" && typeof window.helpdeskEnhanceSteps === "function") {
  window.helpdeskEnhanceSteps(bubble);
}
```

Also expose two helpers the new JS expects. Find where `threadId` is declared as a `let` or `const` in the inline JS (search `let threadId` or `const threadId`). Right after that declaration, add:

```javascript
window.__HELPDESK_THREAD_ID__ = threadId;
```

And right after the existing function that sends a message to the chat (search `submitChatCore` for context), expose a simple submit helper:

```javascript
window.helpdeskSubmitChat = async function (text) {
  if (!text) return;
  addMessage("user", text, { isMarkdown: false });
  try { await submitChatCore({ message: text, screenshots: [], interaction: undefined }); } catch (_) {}
};
```

If you can't locate the exact spot, place this helper at the very end of the inline `<script>` block before the closing `</script>` — it must run after `submitChatCore` and `addMessage` are defined.

- [ ] **Step 3: Append CSS**

Append to `helpdesk_app/static/app.css`:

```css
.step-cards { display: flex; flex-direction: column; gap: 8px; margin: 12px 0; }
.step-card { border: 1px solid var(--border, #d8dee8); border-radius: 8px; padding: 10px 12px; background: var(--panel, #fff); transition: border-color .15s, background .15s; }
.step-card[data-status="current"] { border-color: var(--accent, #1d6bc4); box-shadow: 0 0 0 2px rgba(29,107,196,.12); }
.step-card[data-status="done"] { opacity: .7; background: #f1faf3; border-color: #b2e1c0; }
.step-card[data-status="done"] .step-text { text-decoration: line-through; color: var(--muted, #5c6b7f); }
.step-card[data-status="stuck"] { background: #fdf2f2; border-color: #f4b8b8; }
.step-card .step-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.step-card .step-num { font-weight: 600; min-width: 22px; height: 22px; line-height: 22px; text-align: center; border-radius: 50%; background: var(--elev, #f7f9fc); border: 1px solid var(--border, #d8dee8); font-size: 12px; }
.step-card .step-status-icon { font-size: 16px; }
.step-card .step-text { flex: 1; }
.step-card .step-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.step-card .step-actions button { font-size: 12px; padding: 4px 10px; border: 1px solid var(--border, #d8dee8); background: var(--elev, #f7f9fc); border-radius: 6px; cursor: pointer; }
.step-card .step-actions button:hover { background: #eaf0f7; }
.step-card .btn-done { color: #1f8a4d; }
.step-card .btn-stuck { color: #b3261e; }
.step-card .step-stuck-form { margin-top: 8px; padding: 8px; background: #fff7f7; border-top: 1px dashed #f4b8b8; border-radius: 6px; }
.step-card .step-stuck-form textarea { width: 100%; box-sizing: border-box; min-height: 60px; font-size: 13px; border: 1px solid var(--border, #d8dee8); border-radius: 4px; padding: 6px; resize: vertical; }
.step-card .step-stuck-actions { display: flex; gap: 6px; margin-top: 6px; justify-content: flex-end; }
.step-card .step-stuck-actions button { font-size: 12px; padding: 4px 10px; border: 0; border-radius: 4px; cursor: pointer; }
.step-card .btn-stuck-send { background: #b3261e; color: #fff; }
.step-card .btn-stuck-cancel { background: #95a5a6; color: #fff; }
.step-card .btn-stuck-shot { background: var(--elev, #f7f9fc); color: var(--text, #1a2332); border: 1px solid var(--border, #d8dee8); }
.step-cards-footer { display: flex; justify-content: flex-end; margin: 4px 0 12px; }
.step-cards-footer .btn-feedback { font-size: 12px; padding: 4px 10px; border: 1px solid var(--border, #d8dee8); background: var(--elev, #f7f9fc); border-radius: 6px; cursor: pointer; }
```

- [ ] **Step 4: Smoke test boot**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8795 ../.venv/bin/python3 run.py &
SP=$!
sleep 6
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8795/static/step_cards.js
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8795/
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Both expected 200.

- [ ] **Step 5: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/static/step_cards.js helpdesk_app/templates/index.html helpdesk_app/static/app.css
git commit -m "feat(ui): step-cards render + stuck inline form"
```

---

## Task 4: System prompt — respect step state

**Files:**
- Modify: `helpdesk_app/graph.py`

- [ ] **Step 1: Append a section about step state to `SYSTEM_PROMPT`**

Find the closing triple-quote of `SYSTEM_PROMPT` in `helpdesk_app/graph.py`. Just before it, append:

```
### Estado de pasos del usuario
- Si el último mensaje del usuario empieza por **[Estado de pasos]**, ese bloque resume qué pasos previos marcó: ✓ hecho, ✕ atascado (con nota corta), ◯ pendiente. **NO repitas pasos ya marcados como ✓**. Si hay un ✕ con nota, da sub-pasos para ese punto.
- Cuando el usuario envíe **[Paso N atascado] "..."** seguido de "Lo que veo:", trátalo como un `step_failed` con contexto: produce un `### Ajuste al paso N` con alternativas concretas y verifica si conviene marcar el ticket en `pendiente_validacion`.
- Cuando el usuario envíe **[Estado de pasos actualizado]**, simplemente revisa el progreso visible y devuelve el siguiente micro-paso (sin reescribir todo el plan).
```

- [ ] **Step 2: Verify prompt still loads**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
../.venv/bin/python3 -c "from helpdesk_app.graph import SYSTEM_PROMPT; assert '[Estado de pasos]' in SYSTEM_PROMPT and 'atascado' in SYSTEM_PROMPT; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/graph.py
git commit -m "feat(prompt): teach LLM to respect step status block + stuck context"
```

---

## Task 5: Widgets — choice + severity

**Files:**
- Create: `helpdesk_app/static/widgets.js`
- Modify: `helpdesk_app/graph.py`
- Modify: `helpdesk_app/static/app.css`

- [ ] **Step 1: Create `helpdesk_app/static/widgets.js`**

```javascript
/* Render de widgets adicionales emitidos por la IA dentro del bloque `helpdesk-ui`:
 *  - choice (opción única radio-style) → al pulsar, envía mensaje al chat
 *  - severity (slider 1..5 con etiquetas) → silencioso, guarda como nota de paso virtual
 *
 * Hook de entrada: livesheet.js parsea el bloque y luego dispara `helpdesk:ui-block`
 * con detail.data. Si no existe ese evento, exponemos `window.helpdeskRenderWidgets(data, container)`
 * que la inline JS puede invocar manualmente.
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
      // Silent: store as a "virtual step" stuck-note on a fake message id so the LLM sees it.
      const tid = (window.__HELPDESK_THREAD_ID__ || "");
      if (!tid) return;
      fetch("/api/steps/register", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: tid, message_id: "_severity_" + (data.id || "imp"), steps: [{ index: 0, text: data.prompt || "severity" }] }),
      }).then(() => fetch("/api/steps/update", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: tid, message_id: "_severity_" + (data.id || "imp"),
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

  // Optional: react to a custom event LiveSheet may dispatch.
  document.addEventListener("helpdesk:ui-block", (ev) => {
    const { data, container } = ev.detail || {};
    if (data && container) renderWidgets(data, container);
  });
})();
```

- [ ] **Step 2: Append widget styles to `helpdesk_app/static/app.css`**

```css
.widget-choice, .widget-severity { border: 1px solid var(--border, #d8dee8); background: var(--elev, #f7f9fc); border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.widget-prompt { font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text, #1a2332); }
.widget-choice-list { display: flex; gap: 6px; flex-wrap: wrap; }
.widget-choice-opt { font-size: 12px; padding: 6px 12px; border: 1px solid var(--border, #d8dee8); background: var(--panel, #fff); border-radius: 16px; cursor: pointer; }
.widget-choice-opt:hover { background: #eaf0f7; }
.widget-severity input[type="range"] { width: 100%; }
.widget-severity-label { font-size: 12px; color: var(--muted, #5c6b7f); margin-top: 4px; }
```

- [ ] **Step 3: Update `SYSTEM_PROMPT` to teach widgets**

In `helpdesk_app/graph.py`, find the section that documents the `helpdesk-ui` block (search for `helpdesk-ui` in the prompt). Right after the `kanban` and `sliders` description, insert:

```
- **choice** (opción única, JSON: `{"choice":{"id":"err","prompt":"¿qué error ves?","options":[{"id":"a","label":"…"}]}}`) cuando convenga acotar el diagnóstico con 2-5 opciones excluyentes. No uses choice si la pregunta es abierta. Máx 5 opciones.
- **severity** (slider gravedad 1-5, JSON: `{"severity":{"id":"imp","prompt":"¿cuánto te bloquea?","labels":["...","...","...","...","..."]}}`) al abrir un ticket para captar prioridad real. Las 5 etiquetas deben ir de menos a más grave.
```

- [ ] **Step 4: Verify prompt**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
../.venv/bin/python3 -c "from helpdesk_app.graph import SYSTEM_PROMPT; assert 'choice' in SYSTEM_PROMPT and 'severity' in SYSTEM_PROMPT; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Wire widgets render after parsing `helpdesk-ui` block**

In `helpdesk_app/static/livesheet.js`, find where the parsed `helpdesk-ui` JSON is consumed (search for `kanban` or `parseUiBlock`). After the existing render logic, dispatch the event:

```javascript
if (typeof document !== "undefined") {
  document.dispatchEvent(new CustomEvent("helpdesk:ui-block", { detail: { data: parsedData, container: containerEl } }));
}
```

`parsedData` and `containerEl` must be replaced with the actual variable names from `livesheet.js`. If the file structure doesn't expose them cleanly, append the dispatch right after the function that renders the kanban (so any extra fields like `choice`/`severity` get rendered into the same container).

If `livesheet.js` is too tangled to safely modify, accept a degraded mode: the inline JS in `index.html` can call `window.helpdeskRenderWidgets(parsed, bubble)` directly after rendering an assistant bubble that contains a `helpdesk-ui` block. Document this fallback in the commit message.

- [ ] **Step 6: Smoke boot**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8796 ../.venv/bin/python3 run.py &
SP=$!
sleep 6
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8796/static/widgets.js
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8796/
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Both expected 200.

- [ ] **Step 7: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/static/widgets.js helpdesk_app/static/app.css helpdesk_app/static/livesheet.js helpdesk_app/graph.py
git commit -m "feat(widgets): choice + severity rendered from helpdesk-ui blocks"
```

---

## Task 6: E2E smoke + checklist update

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 -m pytest tests/ -v
```

Expected: all pass (10 from earlier + 8 new step_state tests = 18 total).

- [ ] **Step 2: Manual smoke (no code change)**

Open the chat in browser (after `run.py` started). Send:

> Mi VPN no conecta.

Wait for the response with `## Plan de acción`. Verify:
1. The numbered list rendered as cards, not plain text.
2. First card is highlighted as "current".
3. Click "✓ Hecho" on step 1 — instantly turns green, no chat noise; step 2 becomes current.
4. Click "✕ Atascado" on step 2 — form opens; type "no aparece la opción de servidor"; Send — message appears in chat with `[Paso 2 atascado]` prefix; LLM responds with sub-steps.
5. Click "📨 Pedir comentario" — short message goes to LLM, responds briefly.

- [ ] **Step 3: Add to `docs/demo-checklist.md`**

Append a section right after the "Demo RAG rápido" section:

```markdown
## Demo step-cards
- [ ] En el chat: "Mi VPN no conecta."
- [ ] Las opciones del plan deben aparecer como tarjetas (no lista numerada plana).
- [ ] Marcar paso 1 como ✓ — debe ser instantáneo (sin nuevo turno del LLM).
- [ ] Marcar paso 2 como ✕ Atascado con nota corta — el LLM responde con `### Ajuste al paso 2`.
- [ ] Si el LLM emite `choice` o `severity`, el widget aparece debajo del mensaje y es interactivo.
```

- [ ] **Step 4: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add docs/demo-checklist.md
git commit -m "docs(demo): step-cards smoke section"
```

---

## Self-review notes

- **Spec coverage:** §4 step state store + endpoints (Tasks 1-2), §5 step-cards (Task 3), §5.4 rehydration (deferred: not implemented because we don't save thread→DOM mapping; documented as known gap — on page reload, cards reset to pending. Acceptable for academic demo, noted as a follow-up). §6 widgets (Task 5). §7 modo guiado compatibility (the guidedBar code is untouched, so it still works alongside). §10 plan order respected.
- **Placeholder scan:** every step has concrete code or commands.
- **Type consistency:** `Status` literal aligned (`pending|done|stuck`), `message_id` used everywhere, `index` 0-based across backend and frontend.
- **Rehydration gap:** if the user reloads, `step_state` persists in process but the DOM is rebuilt fresh. The `helpdeskEnhanceSteps` will assign a NEW `msg_id` to the same content, so the prior status is lost. This is acceptable for the demo timeline; a real fix would require stable `msg_id` derived from message content hash + position, which is out of scope.
- **`helpdeskSubmitChat` race:** if the inline JS hasn't initialized when `step_cards.js` runs (defer order), buttons fall back to populating the textarea — degraded but not broken.
