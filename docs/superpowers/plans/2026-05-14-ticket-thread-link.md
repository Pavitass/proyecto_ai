# Tickets ↔ Thread Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link every ticket to the conversation that created it (`thread_id`), expose two filtered views in the sidebar ("Esta conversación" / "Todos"), and add a detail modal with all ticket fields.

**Architecture:** SQLite migration adds a nullable `thread_id` column. A new `ContextVar` carries the active `thread_id` into the LangGraph tool runtime so `crear_ticket_de_servicio` can persist it without changing the LLM-visible tool signature. The existing `/api/tickets` endpoint accepts a `?thread_id=` query param. Frontend adds tab buttons, priority chips, and a detail modal — all reusing existing endpoints.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (sqlite3 stdlib), Pydantic v2, vanilla JS.

---

## File Structure

**Modify:**
- `helpdesk_app/db.py` — migration adds `thread_id`, helpers for filtered list
- `helpdesk_app/chat_context.py` — add `chat_thread_id: ContextVar[str]`
- `helpdesk_app/main.py` — set contextvar in `/api/chat`, accept `?thread_id=` in `/api/tickets`
- `helpdesk_app/tools.py` — `crear_ticket_de_servicio` reads contextvar and passes to `db.crear_ticket`
- `helpdesk_app/templates/index.html` — tabs in sidebar, priority chips on cards, detail modal
- `helpdesk_app/static/app.css` — styles for `.tickets-tabs`, `.priority-chip-{alta,media,baja}`, `#ticketModal`

**Test:**
- `tests/test_ticket_thread.py` — migration applies cleanly; `crear_ticket(thread_id=…)` persists; `listar_tickets_por_thread()` filters.

---

## Task 1: SQLite migration + db helpers (TDD)

**Files:**
- Modify: `helpdesk_app/db.py`
- Test: `tests/test_ticket_thread.py` (create)

- [ ] **Step 1: Failing test**

Create `tests/test_ticket_thread.py`:

```python
import os
import tempfile
import importlib

import pytest


@pytest.fixture
def fresh_db(monkeypatch):
    """Point the db module at a brand-new sqlite file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    monkeypatch.setenv("HELPDESK_SQLITE_PATH_OVERRIDE", "")  # placeholder, unused
    # Patch the path at the module level.
    from helpdesk_app import config, db
    monkeypatch.setattr(config, "SQLITE_PATH", __import__("pathlib").Path(tmp.name))
    monkeypatch.setattr(db, "SQLITE_PATH", __import__("pathlib").Path(tmp.name))
    db.init_db()
    yield db
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def test_migration_adds_thread_id_column(fresh_db):
    import sqlite3
    from helpdesk_app.config import SQLITE_PATH
    conn = sqlite3.connect(str(SQLITE_PATH))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tickets)").fetchall()}
    conn.close()
    assert "thread_id" in cols


def test_crear_ticket_persists_thread_id(fresh_db):
    tid = fresh_db.crear_ticket(
        titulo="VPN no conecta", categoria="red", prioridad="alta",
        descripcion_usuario="no entra", pasos_sugeridos="probar",
        fuentes_kb=[], estado="en_diagnostico", thread_id="thr-abc",
    )
    got = fresh_db.obtener_ticket(tid)
    assert got is not None
    assert got["thread_id"] == "thr-abc"


def test_crear_ticket_without_thread_id_stores_null(fresh_db):
    tid = fresh_db.crear_ticket(
        titulo="x", categoria="y", prioridad="baja",
        descripcion_usuario="z", pasos_sugeridos="w",
        fuentes_kb=[], estado="abierto",
    )
    got = fresh_db.obtener_ticket(tid)
    assert got is not None
    assert got["thread_id"] is None


def test_listar_tickets_por_thread_filters(fresh_db):
    a = fresh_db.crear_ticket(titulo="a", categoria="c", prioridad="alta", descripcion_usuario="d", pasos_sugeridos="p", fuentes_kb=[], estado="abierto", thread_id="thr-1")
    b = fresh_db.crear_ticket(titulo="b", categoria="c", prioridad="alta", descripcion_usuario="d", pasos_sugeridos="p", fuentes_kb=[], estado="abierto", thread_id="thr-2")
    c = fresh_db.crear_ticket(titulo="c", categoria="c", prioridad="alta", descripcion_usuario="d", pasos_sugeridos="p", fuentes_kb=[], estado="abierto")  # no thread
    only1 = fresh_db.listar_tickets_por_thread("thr-1")
    ids = {t["id"] for t in only1}
    assert a in ids and b not in ids and c not in ids


def test_listar_tickets_includes_thread_id_field(fresh_db):
    fresh_db.crear_ticket(titulo="a", categoria="c", prioridad="alta", descripcion_usuario="d", pasos_sugeridos="p", fuentes_kb=[], estado="abierto", thread_id="thr-1")
    all_t = fresh_db.listar_tickets(10)
    assert all_t and "thread_id" in all_t[0]
```

- [ ] **Step 2: Verify failure**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
../.venv/bin/python3 -m pytest tests/test_ticket_thread.py -v
```

Expected: fails — `thread_id` not in column list and `crear_ticket` doesn't accept `thread_id`.

- [ ] **Step 3: Add migration + helpers in `helpdesk_app/db.py`**

In `_migrate_tickets_schema` (around line 43), add after the existing two ALTER blocks:

```python
    if "thread_id" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN thread_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_thread ON tickets(thread_id)")
```

In `crear_ticket` (around line 51), change the signature to accept `thread_id` and pass it in the INSERT:

Replace the existing function with:

```python
def crear_ticket(
    titulo: str,
    categoria: str,
    prioridad: str,
    descripcion_usuario: str,
    pasos_sugeridos: str,
    fuentes_kb: list[str],
    estado: str = "abierto",
    thread_id: str | None = None,
) -> str:
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = _conn()
    try:
        conn.execute(
            """
            INSERT INTO tickets (
                id, titulo, categoria, prioridad, descripcion_usuario,
                pasos_sugeridos, fuentes_kb, estado, motivo_escalacion, created_at, thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tid,
                titulo.strip(),
                categoria.strip(),
                prioridad.strip(),
                descripcion_usuario.strip(),
                pasos_sugeridos.strip(),
                json.dumps(fuentes_kb, ensure_ascii=False),
                estado,
                None,
                now,
                (thread_id or None) and thread_id.strip() or None,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return tid
```

After the existing `listar_tickets` function (around line 143), add:

```python
def listar_tickets_por_thread(thread_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM tickets WHERE thread_id = ? ORDER BY datetime(created_at) DESC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
```

- [ ] **Step 4: Verify pass**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
../.venv/bin/python3 -m pytest tests/test_ticket_thread.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/db.py tests/test_ticket_thread.py
git commit -m "feat(db): tickets.thread_id column + per-thread listing"
```

---

## Task 2: Contextvar + wiring

**Files:**
- Modify: `helpdesk_app/chat_context.py`
- Modify: `helpdesk_app/main.py`
- Modify: `helpdesk_app/tools.py`

- [ ] **Step 1: Add contextvar in `helpdesk_app/chat_context.py`**

Open the file. After the existing `chat_client_os` definition, append:

```python
chat_thread_id: ContextVar[str] = ContextVar("chat_thread_id", default="")
```

- [ ] **Step 2: Set the contextvar in `/api/chat`**

Open `helpdesk_app/main.py`, find the `chat()` handler (the function with `@app.post("/api/chat")` decorator near line 326). At the very top of the function body, before any other logic, add:

```python
    _token_thread = chat_ctx.chat_thread_id.set(body.thread_id)
    try:
```

And wrap the entire function body. Just before the existing `return` statement(s), the matching `finally` must reset the token. The cleanest way:

Find the structure of the function. If it ends with one `return` at the bottom, transform it into:

```python
def chat(body: ChatIn):
    _token_thread = chat_ctx.chat_thread_id.set(body.thread_id)
    try:
        # ... entire existing body ...
        return ChatOut(...)
    finally:
        chat_ctx.chat_thread_id.reset(_token_thread)
```

If there are multiple early returns or HTTPException raises, the `try/finally` still works because `finally` runs in all exits. Indent every line of the existing body by one level inside the `try:` block.

If the function is long and indenting risks errors, instead use a context manager. Append once near top:

```python
from contextlib import contextmanager

@contextmanager
def _bind_thread(tid: str):
    tok = chat_ctx.chat_thread_id.set(tid)
    try:
        yield
    finally:
        chat_ctx.chat_thread_id.reset(tok)
```

Then wrap the body of `chat()`:

```python
def chat(body: ChatIn):
    with _bind_thread(body.thread_id):
        # ... entire existing body ...
```

Pick whichever is less invasive on the existing code.

- [ ] **Step 3: Make `crear_ticket_de_servicio` read the contextvar**

Open `helpdesk_app/tools.py`. Find `crear_ticket_de_servicio` (around line 138). Locate the call to `db.crear_ticket(...)` inside it. Add a line that reads the contextvar just above, and pass it:

```python
    _tid_ctx = (chat_ctx_module.chat_thread_id.get() or "") or None
```

(Use the actual imported alias for `chat_context`. Looking at the file's existing imports: `from helpdesk_app.chat_context import chat_client_os`. Augment it to also import `chat_thread_id`. The simplest edit: change that import line to `from helpdesk_app import chat_context as chat_ctx` and use `chat_ctx.chat_thread_id.get()`. Then update any existing references to `chat_client_os` within `tools.py` accordingly.)

Then pass `thread_id=_tid_ctx` to `db.crear_ticket`:

```python
    tid = db.crear_ticket(
        titulo=titulo,
        categoria=categoria,
        prioridad=prioridad,
        descripcion_usuario=descripcion_usuario,
        pasos_sugeridos=pasos_sugeridos,
        fuentes_kb=fuentes,
        estado=est,
        thread_id=_tid_ctx,
    )
```

- [ ] **Step 4: Smoke test**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8798 ../.venv/bin/python3 run.py > /tmp/hd_tikt2.log 2>&1 &
SP=$!
sleep 15
# Send a synthetic chat that triggers ticket creation
THREAD_ID="thr-test-$$"
curl -s -X POST http://127.0.0.1:8798/api/chat -H 'Content-Type: application/json' \
  -d "{\"thread_id\":\"$THREAD_ID\",\"message\":\"Mi VPN no conecta cuando trabajo desde casa, me da error de certificado expirado.\",\"screenshots\":[]}" \
  > /tmp/hd_tikt2_chat.json 2>&1 || true
sleep 2
# Check if a ticket got created with the thread_id
../.venv/bin/python3 -c "
from helpdesk_app import db
rows = db.listar_tickets_por_thread('$THREAD_ID')
print('tickets in thread:', len(rows))
if rows:
    print('  first ticket id:', rows[0]['id'], 'titulo:', rows[0]['titulo'])
"
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Expected: at least 1 ticket created with the synthetic thread_id (the agent should create one because the message describes a concrete incident).

If the agent doesn't create a ticket (LLM judgment), don't fail — instead verify manually via the chat UI later. Report what you saw.

- [ ] **Step 5: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/chat_context.py helpdesk_app/main.py helpdesk_app/tools.py
git commit -m "feat(tickets): inject thread_id via contextvar into crear_ticket"
```

---

## Task 3: `/api/tickets` filter

**Files:**
- Modify: `helpdesk_app/main.py`

- [ ] **Step 1: Edit `/api/tickets` to accept query param**

Open `helpdesk_app/main.py`. Find:

```python
@app.get("/api/tickets")
def list_tickets():
    return {"tickets": db.listar_tickets(80)}
```

Replace with:

```python
@app.get("/api/tickets")
def list_tickets(thread_id: str | None = None):
    if thread_id:
        return {"tickets": db.listar_tickets_por_thread(thread_id.strip(), 80)}
    return {"tickets": db.listar_tickets(80)}
```

- [ ] **Step 2: Smoke test**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8799 ../.venv/bin/python3 run.py > /tmp/hd_tikt3.log 2>&1 &
SP=$!
sleep 15
ALL=$(curl -s http://127.0.0.1:8799/api/tickets | ../.venv/bin/python3 -c "import sys,json; print(len(json.load(sys.stdin)['tickets']))")
echo "all: $ALL"
FILT=$(curl -s 'http://127.0.0.1:8799/api/tickets?thread_id=nonexistent-thread-zz' | ../.venv/bin/python3 -c "import sys,json; print(len(json.load(sys.stdin)['tickets']))")
echo "filtered nonexistent: $FILT"
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Expected: `all: <N>` where N is whatever exists in db; `filtered nonexistent: 0`.

- [ ] **Step 3: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/main.py
git commit -m "feat(api): /api/tickets accepts optional thread_id filter"
```

---

## Task 4: UI tabs + improved cards

**Files:**
- Modify: `helpdesk_app/templates/index.html`
- Modify: `helpdesk_app/static/app.css`

- [ ] **Step 1: Locate the existing tickets panel in `helpdesk_app/templates/index.html`**

Run: `grep -n 'TICKETS\|ticketsList\|loadTickets' /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent/helpdesk_app/templates/index.html | head -20`

Find the markup that lists tickets in the sidebar (likely a `<div class="panel">` containing the heading "TICKETS RECIENTES" and a list element).

- [ ] **Step 2: Replace the panel markup**

Replace the existing tickets panel block with:

```html
<div class="panel" id="ticketsPanel">
  <div class="tickets-header">
    <h3>Tickets</h3>
    <div class="tickets-tabs">
      <button type="button" class="tab-btn active" data-scope="thread">Esta conversación</button>
      <button type="button" class="tab-btn" data-scope="all">Todos</button>
    </div>
  </div>
  <div class="tickets" id="ticketsList"></div>
</div>
```

Preserve any existing IDs that other code references (e.g. if `ticketsList` already exists with a different id, keep it).

- [ ] **Step 3: Update / add `loadTickets` in the inline JS**

Find the existing function `loadTickets` in the inline `<script>` block. Replace its body with:

```javascript
    let _ticketsScope = "thread";

    async function loadTickets() {
      const tid = window.__HELPDESK_THREAD_ID__ || "";
      const url = (_ticketsScope === "thread" && tid)
        ? "/api/tickets?thread_id=" + encodeURIComponent(tid)
        : "/api/tickets";
      let data = { tickets: [] };
      try {
        const r = await fetch(url);
        if (r.ok) data = await r.json();
      } catch (_) {}
      const root = document.getElementById("ticketsList");
      if (!root) return;
      root.innerHTML = "";
      if (!data.tickets || !data.tickets.length) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.style.padding = "8px 4px";
        empty.textContent = _ticketsScope === "thread"
          ? "Sin tickets en esta conversación todavía."
          : "Sin tickets registrados.";
        root.appendChild(empty);
        return;
      }
      for (const t of data.tickets) {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "ticket";
        card.dataset.id = t.id;
        const prio = (t.prioridad || "").toLowerCase();
        const chipClass = ["alta","media","baja"].includes(prio) ? prio : "neutral";
        card.innerHTML = `
          <div class="ticket-row1">
            <span class="ticket-title">${(t.titulo || "(sin título)").replace(/</g,"&lt;")}</span>
            <span class="priority-chip priority-${chipClass}">${prio || "—"}</span>
          </div>
          <div class="ticket-row2">
            <span class="ticket-cat">${(t.categoria || "").replace(/</g,"&lt;")}</span>
            <span class="ticket-state">${(t.estado || "").replace(/</g,"&lt;")}</span>
          </div>
          <code class="ticket-id">${String(t.id || "").slice(0, 8)}…</code>
        `;
        card.addEventListener("click", () => {
          if (typeof window.helpdeskOpenTicket === "function") {
            window.helpdeskOpenTicket(t.id);
          }
        });
        root.appendChild(card);
      }
    }
```

Then wire the tabs. Right after `loadTickets` (or anywhere after the DOM is ready), add:

```javascript
    document.querySelectorAll(".tickets-tabs .tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tickets-tabs .tab-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        _ticketsScope = btn.dataset.scope || "thread";
        loadTickets();
      });
    });
```

- [ ] **Step 4: Append CSS to end of `helpdesk_app/static/app.css`**

```css

/* Tickets tabs + chips ----- */
.tickets-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
.tickets-tabs { display: flex; gap: 4px; }
.tickets-tabs .tab-btn { font-size: 0.7rem; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border); background: var(--elev); color: var(--muted); cursor: pointer; font-family: inherit; }
.tickets-tabs .tab-btn.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.ticket-row1 { display: flex; justify-content: space-between; gap: 6px; align-items: center; }
.ticket-row2 { display: flex; gap: 8px; font-size: 0.72rem; color: var(--muted); margin-top: 2px; }
.ticket-title { font-weight: 600; font-size: 0.82rem; flex: 1; text-align: left; word-break: break-word; }
.priority-chip { font-size: 0.65rem; padding: 2px 8px; border-radius: 999px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.04em; }
.priority-alta { background: #fde2e1; color: #b3261e; }
.priority-media { background: #fdf3d8; color: #8a5a00; }
.priority-baja { background: #e2e8ef; color: #4a5a73; }
.priority-neutral { background: var(--elev); color: var(--muted); }
.ticket-id { font-size: 0.65rem; color: var(--accent); }
```

- [ ] **Step 5: Smoke boot**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8800 ../.venv/bin/python3 run.py > /tmp/hd_tikt4.log 2>&1 &
SP=$!
sleep 12
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8800/
curl -sf http://127.0.0.1:8800/ | grep -c 'tickets-tabs'
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Expected: 200; count of `tickets-tabs` >= 1.

- [ ] **Step 6: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/templates/index.html helpdesk_app/static/app.css
git commit -m "feat(ui): tickets sidebar tabs + priority chips"
```

---

## Task 5: UI ticket detail modal

**Files:**
- Modify: `helpdesk_app/templates/index.html`
- Modify: `helpdesk_app/static/app.css`

- [ ] **Step 1: Append modal HTML at the bottom of `index.html`, before `</body>`**

```html
<div id="ticketModal" hidden role="dialog" aria-modal="true">
  <div class="tk-modal-card">
    <button type="button" class="tk-close" aria-label="Cerrar">×</button>
    <div class="tk-head">
      <h3 id="tkTitle">…</h3>
      <div class="tk-chips">
        <span id="tkPriority" class="priority-chip">—</span>
        <span id="tkCategory" class="muted-chip">—</span>
        <span id="tkState" class="muted-chip">—</span>
      </div>
      <code id="tkId" class="muted"></code>
    </div>
    <section class="tk-section">
      <h4>Descripción</h4>
      <pre id="tkDesc"></pre>
    </section>
    <section class="tk-section">
      <h4>Pasos sugeridos</h4>
      <pre id="tkSteps"></pre>
    </section>
    <section class="tk-section">
      <h4>Fuentes KB</h4>
      <ul id="tkSources"></ul>
    </section>
    <section class="tk-section" id="tkResolutionWrap" hidden>
      <h4>Resolución</h4>
      <pre id="tkResolution"></pre>
    </section>
    <footer class="tk-foot">
      <span id="tkDates" class="muted"></span>
      <div class="tk-actions">
        <button type="button" id="tkClose2" class="btn-ghost">Cerrar</button>
        <button type="button" id="tkContinue" class="btn-primary">Continuar en chat</button>
      </div>
    </footer>
  </div>
</div>
```

- [ ] **Step 2: Append CSS**

Append to `helpdesk_app/static/app.css`:

```css

/* Ticket detail modal ----- */
#ticketModal { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; z-index: 10001; padding: 20px; }
#ticketModal[hidden] { display: none !important; }
#ticketModal .tk-modal-card { background: var(--panel, #fff); width: 100%; max-width: 720px; max-height: 85vh; overflow: auto; border-radius: 12px; padding: 20px; box-shadow: 0 10px 40px rgba(0,0,0,.3); position: relative; }
#ticketModal .tk-close { position: absolute; right: 10px; top: 10px; background: transparent; border: 0; font-size: 24px; cursor: pointer; color: var(--muted); }
#ticketModal .tk-head h3 { margin: 0 0 8px; font-size: 1.1rem; }
#ticketModal .tk-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
#ticketModal .muted-chip { font-size: 0.7rem; padding: 2px 8px; border-radius: 999px; background: var(--elev); border: 1px solid var(--border); color: var(--muted); }
#ticketModal .tk-section { margin-top: 14px; }
#ticketModal .tk-section h4 { margin: 0 0 4px; font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
#ticketModal .tk-section pre { background: var(--elev); border: 1px solid var(--border); border-radius: 8px; padding: 10px; white-space: pre-wrap; word-break: break-word; font-size: 0.85rem; font-family: var(--font); margin: 0; }
#ticketModal .tk-section ul { margin: 0; padding-left: 20px; font-size: 0.85rem; }
#ticketModal .tk-foot { margin-top: 18px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
#ticketModal .tk-actions { display: flex; gap: 8px; }
#ticketModal .btn-primary { background: var(--accent); color: #fff; border: 0; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-family: inherit; font-size: 0.85rem; }
```

- [ ] **Step 3: Wire JS in inline script**

Find a spot in the inline `<script>` block after the rest of the JS is set up (a good anchor is just before `loadTickets();` is called for the first time). Insert:

```javascript
    async function openTicketModal(ticketId) {
      const modal = document.getElementById("ticketModal");
      try {
        const r = await fetch("/api/tickets/" + encodeURIComponent(ticketId));
        if (!r.ok) return;
        const t = await r.json();
        document.getElementById("tkTitle").textContent = t.titulo || "(sin título)";
        const prio = (t.prioridad || "").toLowerCase();
        const prioEl = document.getElementById("tkPriority");
        prioEl.textContent = prio || "—";
        prioEl.className = "priority-chip priority-" + (["alta","media","baja"].includes(prio) ? prio : "neutral");
        document.getElementById("tkCategory").textContent = t.categoria || "—";
        document.getElementById("tkState").textContent = t.estado || "—";
        document.getElementById("tkId").textContent = "ID: " + (t.id || "");
        document.getElementById("tkDesc").textContent = t.descripcion_usuario || "";
        document.getElementById("tkSteps").textContent = t.pasos_sugeridos || "";
        const ul = document.getElementById("tkSources");
        ul.innerHTML = "";
        (t.fuentes_kb || []).forEach((src) => {
          const li = document.createElement("li");
          li.textContent = src;
          ul.appendChild(li);
        });
        const resWrap = document.getElementById("tkResolutionWrap");
        const resEl = document.getElementById("tkResolution");
        if (t.resolucion_final) {
          resEl.textContent = t.resolucion_final;
          resWrap.removeAttribute("hidden");
        } else {
          resWrap.setAttribute("hidden", "");
        }
        const parts = [];
        if (t.created_at) parts.push("Creado: " + new Date(t.created_at).toLocaleString());
        if (t.resolved_at) parts.push("Resuelto: " + new Date(t.resolved_at).toLocaleString());
        document.getElementById("tkDates").textContent = parts.join(" · ");
        modal._currentTicketId = t.id;
        modal.removeAttribute("hidden");
      } catch (_) {}
    }

    window.helpdeskOpenTicket = openTicketModal;

    (function () {
      const modal = document.getElementById("ticketModal");
      if (!modal) return;
      function close() { modal.setAttribute("hidden", ""); }
      modal.querySelector(".tk-close").addEventListener("click", close);
      document.getElementById("tkClose2").addEventListener("click", close);
      modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
      document.getElementById("tkContinue").addEventListener("click", () => {
        const id = modal._currentTicketId || "";
        const msgEl = document.getElementById("msg");
        if (msgEl) {
          msgEl.value = "[Ticket " + String(id).slice(0, 8) + "] ";
          msgEl.focus();
          if (typeof syncMsgTextareaHeight === "function") syncMsgTextareaHeight();
        }
        close();
      });
    })();
```

- [ ] **Step 4: Smoke**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8801 ../.venv/bin/python3 run.py > /tmp/hd_tikt5.log 2>&1 &
SP=$!
sleep 12
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8801/
curl -sf http://127.0.0.1:8801/ | grep -c 'ticketModal'
curl -sf http://127.0.0.1:8801/ | grep -c 'helpdeskOpenTicket'
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
```

Expected: 200, both grep counts >= 1.

- [ ] **Step 5: Commit**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/templates/index.html helpdesk_app/static/app.css
git commit -m "feat(ui): ticket detail modal with priority chips + continue-in-chat"
```

---

## Task 6: E2E smoke + docs update

- [ ] **Step 1: full test suite**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 -m pytest tests/ -v
```

Expected: all pass (≥ 24 tests = 19 previous + 5 new).

- [ ] **Step 2: full server smoke**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8802 ../.venv/bin/python3 run.py > /tmp/hd_tikt6.log 2>&1 &
SP=$!
sleep 15
curl -sf -o /dev/null -w "/ -> %{http_code}\n" http://127.0.0.1:8802/
curl -sf -o /dev/null -w "/api/tickets -> %{http_code}\n" http://127.0.0.1:8802/api/tickets
curl -sf -o /dev/null -w "/api/tickets?thread_id=xx -> %{http_code}\n" 'http://127.0.0.1:8802/api/tickets?thread_id=xx'
kill $SP 2>/dev/null; pkill -f 'helpdesk_app.main:app' 2>/dev/null; sleep 1
tail -20 /tmp/hd_tikt6.log
```

All three expected 200; log must show "Application startup complete." and no traceback.

- [ ] **Step 3: append to `docs/demo-checklist.md`**

After the existing "## Demo step-cards" section, add:

```markdown
## Demo tickets por conversación
- [ ] Iniciar nueva sesión.
- [ ] Describir incidencia: "Mi VPN no conecta con error de certificado". El agente debe crear un ticket.
- [ ] Pestaña "Esta conversación" en la barra lateral debe mostrarlo; "Todos" muestra también los previos.
- [ ] Click en el ticket abre modal con título, prioridad coloreada, descripción y pasos sugeridos.
- [ ] Botón "Continuar en chat" precarga `[Ticket abc12345] ` en el textarea.
```

- [ ] **Step 4: commit docs**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add docs/demo-checklist.md
git commit -m "docs(demo): tickets per conversation smoke section"
```

- [ ] **Step 5: print last commits**

```bash
git -C /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent log --oneline -12
```

Report: pytest summary, three HTTP codes, last 10 lines server log, final commit SHA, git log.

---

## Self-review notes

- **Spec coverage:** §4 migration (T1), §5.1 contextvar (T2), §5.2 chat wiring (T2), §5.3-5.4 db + tool wiring (T1-T2), §5.5 endpoint filter (T3), §6.1-6.3 UI (T4-T5). All covered.
- **Placeholders:** all steps have concrete code.
- **Type consistency:** `thread_id: str | None`, `chat_thread_id: ContextVar[str]` default `""` (empty string converted to None at insert), `priority-{alta,media,baja,neutral}` consistent across CSS + JS.
- **Known limitations:** The detail modal endpoint `/api/tickets/{id}` already exists per earlier grep — verify in T5 before assuming the JSON shape; if it returns a different envelope (e.g. wrapped in `{"ticket": {...}}`), adapt `openTicketModal` accordingly.
