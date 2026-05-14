# Vision Loop + RAG Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an agentic vision loop (screenshot → reason → one action → verify, repeated) to the existing helpdesk agent, plus make the RAG faster and more focused (top-k cache, no automatic web fallback).

**Architecture:** New `helpdesk_app/vision_loop/` package exposing a LangGraph tool `ejecutar_tarea_escritorio(goal)`. Inside, a state machine loops up to N times, calling a vision LLM (Gemini via existing `langchain-google-genai`) for one atomic action per turn, executing it through the existing `desktop_exec_py.run_pyautogui_action`. UI listens over SSE and shows live thumbnails + per-step confirmation for sensitive actions. RAG gets a query LRU cache, configurable top_k, MMR option, and startup warm-up; system prompt drops the proactive web fallback.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, langchain-google-genai (Gemini 2.x for vision), Chroma, sentence-transformers (HF embeddings, already default), PyAutoGUI, mss (new dep for fast screenshots), Pydantic v2, Electron renderer + vanilla JS for SSE.

---

## File Structure

**Create:**
- `helpdesk_app/vision_loop/__init__.py` — package init, re-exports
- `helpdesk_app/vision_loop/screen.py` — screen capture + thumbnail
- `helpdesk_app/vision_loop/actor.py` — vision LLM call → `LoopDecision`
- `helpdesk_app/vision_loop/executor.py` — thin wrapper around `desktop_exec_py.run_pyautogui_action`
- `helpdesk_app/vision_loop/events.py` — in-memory pub/sub for SSE + run registry
- `helpdesk_app/vision_loop/loop.py` — state machine orchestrator
- `helpdesk_app/vision_loop/schema.py` — `LoopDecision` Pydantic model
- `tests/test_rag_cache.py` — unit tests for RAG cache + top_k + mmr
- `tests/test_vision_loop_state.py` — unit tests for loop state machine with fake actor
- `tests/test_actor_schema.py` — schema validation for `LoopDecision`
- `docs/demo-checklist.md` — live demo runbook

**Modify:**
- `helpdesk_app/rag.py` — add `top_k`, `mmr`, LRU cache, `invalidate_cache()`, `warmup()`
- `helpdesk_app/main.py` — startup warm-up, SSE endpoints, abort/confirm endpoints
- `helpdesk_app/tools.py` — update `buscar_en_base_de_conocimiento` (top_k, diversidad), add `ejecutar_tarea_escritorio`
- `helpdesk_app/graph.py` — system prompt: no automatic web fallback, mention vision loop tool
- `helpdesk_app/static/app.js` (and the electron equivalent under `electron/ui/`) — live automation panel listening to SSE
- `helpdesk_app/static/styles.css` (or equivalent) — styles for panel and confirm modal
- `requirements.txt` — add `mss>=9.0.0`
- `README.md` — macOS permissions section

---

## Task 1: RAG — top_k + MMR + cache parameters

**Files:**
- Modify: `helpdesk_app/rag.py`
- Test: `tests/test_rag_cache.py` (create)

- [ ] **Step 1: Create the failing test file**

```python
# tests/test_rag_cache.py
import pytest
from helpdesk_app import rag

def test_buscar_contexto_accepts_top_k_and_mmr():
    # Smoke: function signature accepts new kwargs without raising TypeError.
    # We don't assert on results (depends on KB content); we only need to confirm
    # it's callable with the new keyword args.
    try:
        rag.buscar_contexto("vpn no conecta", k=2, mmr=False)
        rag.buscar_contexto("vpn no conecta", k=2, mmr=True)
    except TypeError as e:
        pytest.fail(f"buscar_contexto rejected new kwargs: {e}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_rag_cache.py::test_buscar_contexto_accepts_top_k_and_mmr -v`

Expected: FAIL — current `buscar_contexto` signature is `(consulta, k=4)` and does not accept `mmr`.

- [ ] **Step 3: Update `buscar_contexto` signature and add MMR branch**

In `helpdesk_app/rag.py`, replace the existing `buscar_contexto` function (currently the last function, lines ~159–161) with:

```python
def buscar_contexto(consulta: str, k: int = 4, mmr: bool = False) -> list[Document]:
    vs = get_vectorstore()
    q = (consulta or "").strip()
    if not q:
        return []
    if mmr:
        return vs.max_marginal_relevance_search(q, k=k, fetch_k=max(k * 3, 12))
    return vs.similarity_search(q, k=k)
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_rag_cache.py -v`

Expected: PASS.

- [ ] **Step 5: Commit (skip if not a git repo — note: this project is not currently a git repo; run `git init` first if you want commits)**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
git add helpdesk_app/rag.py tests/test_rag_cache.py
git commit -m "feat(rag): add top_k and mmr params to buscar_contexto"
```

---

## Task 2: RAG — in-memory LRU cache + invalidation

**Files:**
- Modify: `helpdesk_app/rag.py`
- Test: `tests/test_rag_cache.py`

- [ ] **Step 1: Add failing test for cache hit behaviour**

Append to `tests/test_rag_cache.py`:

```python
def test_cache_returns_same_object_on_second_call(monkeypatch):
    rag.invalidate_cache()
    calls = {"n": 0}
    real = rag.get_vectorstore
    def wrapped():
        calls["n"] += 1
        return real()
    monkeypatch.setattr(rag, "get_vectorstore", wrapped)
    a = rag.buscar_contexto("impresora atascada", k=3)
    b = rag.buscar_contexto("impresora atascada", k=3)
    assert a is b, "Cache should return the exact same list object on hit"
    assert calls["n"] == 1, "get_vectorstore should be called only once due to cache"


def test_invalidate_cache_forces_recompute(monkeypatch):
    rag.invalidate_cache()
    calls = {"n": 0}
    real = rag.get_vectorstore
    def wrapped():
        calls["n"] += 1
        return real()
    monkeypatch.setattr(rag, "get_vectorstore", wrapped)
    rag.buscar_contexto("vpn", k=2)
    rag.invalidate_cache()
    rag.buscar_contexto("vpn", k=2)
    assert calls["n"] == 2
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_rag_cache.py -v`

Expected: FAIL on `test_cache_returns_same_object_on_second_call` (no cache) and `test_invalidate_cache_forces_recompute` (no `invalidate_cache` symbol).

- [ ] **Step 3: Add cache and invalidation to `rag.py`**

At top of `helpdesk_app/rag.py`, add module-level cache:

```python
from threading import Lock

_QUERY_CACHE: dict[tuple[str, int, bool], list[Document]] = {}
_QUERY_CACHE_LOCK = Lock()
_QUERY_CACHE_MAX = 64


def invalidate_cache() -> None:
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE.clear()
```

Replace the `buscar_contexto` function from Task 1 with the cached version:

```python
def buscar_contexto(consulta: str, k: int = 4, mmr: bool = False) -> list[Document]:
    q = (consulta or "").strip().lower()
    if not q:
        return []
    key = (q, int(k), bool(mmr))
    with _QUERY_CACHE_LOCK:
        cached = _QUERY_CACHE.get(key)
        if cached is not None:
            return cached
    vs = get_vectorstore()
    if mmr:
        result = vs.max_marginal_relevance_search(q, k=k, fetch_k=max(k * 3, 12))
    else:
        result = vs.similarity_search(q, k=k)
    with _QUERY_CACHE_LOCK:
        if len(_QUERY_CACHE) >= _QUERY_CACHE_MAX:
            # Drop oldest insertion-order entry (Python 3.7+ dict preserves it)
            _QUERY_CACHE.pop(next(iter(_QUERY_CACHE)))
        _QUERY_CACHE[key] = result
    return result
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_rag_cache.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add helpdesk_app/rag.py tests/test_rag_cache.py
git commit -m "feat(rag): add LRU-like query cache with invalidation"
```

---

## Task 3: RAG — startup warm-up

**Files:**
- Modify: `helpdesk_app/rag.py`, `helpdesk_app/main.py`

- [ ] **Step 1: Add `warmup()` helper to `rag.py`**

Append to `helpdesk_app/rag.py`:

```python
def warmup() -> None:
    """Pre-build the vectorstore so the first user query doesn't pay the cold-start cost."""
    try:
        get_vectorstore()
    except Exception as e:  # don't crash the server if KB is empty during dev
        import logging
        logging.getLogger("helpdesk.rag").warning("RAG warmup skipped: %s", e)
```

- [ ] **Step 2: Wire warm-up into FastAPI startup**

In `helpdesk_app/main.py`, replace the existing `startup()` function (around line 49–51):

```python
@app.on_event("startup")
def startup():
    db.init_db()
    from helpdesk_app import rag
    rag.warmup()
```

- [ ] **Step 3: Smoke test the server boot**

Run (in a separate shell, leave running 10s):

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_PORT=8788 ../.venv/bin/python3 run.py
```

Expected log includes Chroma loading messages on startup, no traceback. Stop with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add helpdesk_app/rag.py helpdesk_app/main.py
git commit -m "feat(rag): warm up vectorstore on FastAPI startup"
```

---

## Task 4: System prompt — remove proactive web fallback

**Files:**
- Modify: `helpdesk_app/graph.py:9-90`

- [ ] **Step 1: Edit the SYSTEM_PROMPT to remove the web-fallback bullet**

In `helpdesk_app/graph.py`, locate lines 17–21 (the numbered list under "Comportamiento proactivo"). Replace bullet 2:

```
  2) Si la KB queda **floja** (pocos fragmentos, no cubre el síntoma, o el usuario pide datos recientes /
     versiones nuevas), llama **buscar_en_web** con una consulta **específica** (mejor en español + producto;
     evita en inglés frases solo del tipo «how to turn off …» porque suelen devolver diccionarios irrelevantes).
     **Cita título y URL** de las fuentes que uses en la respuesta.
```

with:

```
  2) Llama **buscar_en_web** SOLO si: (a) el usuario pide explícitamente fuente externa
     ("busca en internet", "fuentes oficiales"), o (b) la KB devolvió **cero** fragmentos relevantes.
     En ese caso avisa antes ("voy a buscar en internet porque…") y **cita título y URL** en la respuesta.
     En cualquier otro caso, no busques en web.
```

- [ ] **Step 2: Add a bullet about the new desktop tool**

Append to the SYSTEM_PROMPT right before the final `"""` (end of the prompt):

```
### Automatización agéntica (loop visual)
- Si el usuario pide **explícitamente** que el sistema **haga algo en su equipo paso a paso viendo la pantalla** (p. ej. "envíalo tú", "hazlo en mi Outlook", "abre Ajustes y cambia X"), llama **ejecutar_tarea_escritorio** con un `goal` corto en español.
- Antes de llamarla, resume el objetivo en lenguaje natural y advierte que cada paso sensible (envío, borrado, ajuste de sistema) requerirá su aprobación.
- No la uses para preguntas informativas ni cuando bastan instrucciones manuales.
```

- [ ] **Step 3: Verify prompt is still a single string (no syntax error)**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -c "from helpdesk_app.graph import SYSTEM_PROMPT; print(len(SYSTEM_PROMPT))"`

Expected: prints an integer > 1500 with no traceback.

- [ ] **Step 4: Commit**

```bash
git add helpdesk_app/graph.py
git commit -m "feat(prompt): drop proactive web fallback; mention vision loop tool"
```

---

## Task 5: Vision loop — `schema.py`

**Files:**
- Create: `helpdesk_app/vision_loop/__init__.py`
- Create: `helpdesk_app/vision_loop/schema.py`
- Test: `tests/test_actor_schema.py` (create)

- [ ] **Step 1: Write failing schema test**

```python
# tests/test_actor_schema.py
import pytest
from pydantic import ValidationError
from helpdesk_app.vision_loop.schema import LoopDecision

def test_done_decision_is_valid_without_action():
    d = LoopDecision(reasoning="ya está", done=True)
    assert d.done is True
    assert d.action is None

def test_action_decision_requires_action_payload():
    d = LoopDecision(
        reasoning="abrir Spotlight",
        action={"type": "hotkey", "keys": ["LeftCmd", "Space"], "delayMs": 400},
    )
    assert d.action.type == "hotkey"

def test_action_must_be_present_unless_terminal():
    with pytest.raises(ValidationError):
        LoopDecision(reasoning="...")  # neither done/fail/needs_user, no action

def test_reasoning_length_capped():
    with pytest.raises(ValidationError):
        LoopDecision(reasoning="x" * 500, done=True)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_actor_schema.py -v`

Expected: FAIL — module `helpdesk_app.vision_loop.schema` does not exist.

- [ ] **Step 3: Create the package init**

```python
# helpdesk_app/vision_loop/__init__.py
"""Loop visual agéntico: capture → reason → one action → verify."""
```

- [ ] **Step 4: Implement schema**

```python
# helpdesk_app/vision_loop/schema.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from helpdesk_app.desktop_plan import DesktopAction


class LoopDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(..., max_length=400)
    action: DesktopAction | None = None
    done: bool = False
    fail: bool = False
    needs_user: bool = False
    reason: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def _exactly_one_outcome(self):
        terminals = [self.done, self.fail, self.needs_user]
        n_terminals = sum(bool(x) for x in terminals)
        if n_terminals > 1:
            raise ValueError("done/fail/needs_user are mutually exclusive")
        if n_terminals == 0 and self.action is None:
            raise ValueError("Either provide an action, or set done/fail/needs_user")
        if n_terminals >= 1 and self.action is not None:
            # Terminal decisions don't carry actions; ignore by clearing.
            self.action = None
        return self
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_actor_schema.py -v`

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add helpdesk_app/vision_loop/__init__.py helpdesk_app/vision_loop/schema.py tests/test_actor_schema.py
git commit -m "feat(vision_loop): add LoopDecision schema"
```

---

## Task 6: Vision loop — `screen.py` (capture + thumbnail)

**Files:**
- Create: `helpdesk_app/vision_loop/screen.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add mss to requirements**

In `helpdesk_app/requirements.txt`, append after the pyautogui line:

```
mss>=9.0.0
Pillow>=10.0.0
```

Then install:

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
../.venv/bin/pip install mss Pillow
```

- [ ] **Step 2: Implement screen module**

```python
# helpdesk_app/vision_loop/screen.py
"""Captura de pantalla rápida con mss + thumbnail con Pillow."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image


@dataclass
class Capture:
    png_b64: str          # full screenshot, PNG base64 (no data: prefix)
    thumb_b64: str        # ~320px wide PNG base64 for UI
    width: int
    height: int


def _capture_pil() -> Image.Image:
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[1]  # primary monitor
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    return img


def _to_png_b64(img: Image.Image, max_side: int | None = None) -> str:
    if max_side and max(img.size) > max_side:
        ratio = max_side / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def capture() -> Capture:
    img = _capture_pil()
    w, h = img.size
    full = _to_png_b64(img, max_side=1280)
    thumb = _to_png_b64(img, max_side=320)
    return Capture(png_b64=full, thumb_b64=thumb, width=w, height=h)
```

- [ ] **Step 3: Smoke test capture**

Run:

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
../.venv/bin/python3 -c "from helpdesk_app.vision_loop.screen import capture; c = capture(); print(c.width, c.height, len(c.png_b64), len(c.thumb_b64))"
```

Expected: prints 4 integers; `len(png_b64)` >> `len(thumb_b64)`; no exception. (On macOS the first run will prompt for Screen Recording permission — grant it, retry.)

- [ ] **Step 4: Commit**

```bash
git add helpdesk_app/vision_loop/screen.py helpdesk_app/requirements.txt
git commit -m "feat(vision_loop): screen capture with mss + thumbnail"
```

---

## Task 7: Vision loop — `executor.py`

**Files:**
- Create: `helpdesk_app/vision_loop/executor.py`

- [ ] **Step 1: Implement thin wrapper**

```python
# helpdesk_app/vision_loop/executor.py
"""Ejecuta una DesktopAction usando el runner PyAutoGUI existente."""
from __future__ import annotations

from helpdesk_app.desktop_exec_py import run_pyautogui_action
from helpdesk_app.desktop_plan import DesktopAction


class ExecutionError(RuntimeError):
    pass


def run(action: DesktopAction) -> None:
    payload = action.model_dump()
    err = run_pyautogui_action(payload)
    if err:
        raise ExecutionError(err)
```

- [ ] **Step 2: Sanity import check**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -c "from helpdesk_app.vision_loop.executor import run, ExecutionError; print('ok')"`

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add helpdesk_app/vision_loop/executor.py
git commit -m "feat(vision_loop): executor wrapper over desktop_exec_py"
```

---

## Task 8: Vision loop — `actor.py` (Gemini vision → one action)

**Files:**
- Create: `helpdesk_app/vision_loop/actor.py`

- [ ] **Step 1: Implement the actor**

```python
# helpdesk_app/vision_loop/actor.py
"""LLM con visión (Gemini) — emite UNA acción por turno."""
from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from helpdesk_app.config import GOOGLE_API_KEY, VISION_MODEL
from helpdesk_app.vision_loop.schema import LoopDecision


_SYSTEM = (
    "Eres un agente que controla un escritorio paso a paso. Mira la captura actual, "
    "el objetivo y el historial; decide UNA sola acción atómica que avance hacia el objetivo. "
    "Responde con un objeto JSON ESTRICTO (sin markdown, sin ```), con esta forma:\n"
    '{"reasoning": "1-3 frases en español",\n'
    ' "action": {"type":"hotkey|move|click|type|wait", ...campos..., "sensitive": false},\n'
    ' "done": false, "fail": false, "needs_user": false, "reason": ""}\n\n'
    "Reglas:\n"
    "- Si el objetivo ya se cumplió en la captura, devuelve done:true y action:null.\n"
    "- Si no puedes avanzar sin el usuario (contraseña, captcha, ambigüedad), needs_user:true y reason.\n"
    "- Si es imposible o peligroso, fail:true y reason.\n"
    "- NUNCA escribas contraseñas. Si la UI las pide, needs_user:true.\n"
    "- Marca sensitive:true en envíos de correos, borrados, ajustes del sistema.\n"
    "- Acciones permitidas (mismo schema que el resto del sistema):\n"
    '  * {"type":"hotkey","keys":["LeftCmd","Space"],"delayMs":400}\n'
    '  * {"type":"move","x":0.5,"y":0.5,"delayMs":200}  (x,y en fracción 0..1)\n'
    '  * {"type":"click","button":"left","delayMs":150}\n'
    '  * {"type":"type","text":"texto","delayMs":120}\n'
    '  * {"type":"wait","delayMs":800}\n'
    "- Las coordenadas (x,y) deben mirar a la imagen real. No inventes coordenadas si el target no está visible.\n"
    "- Una sola acción por respuesta. Nada de listas.\n"
)


@dataclass
class HistoryItem:
    reasoning: str
    action_summary: str   # short text like "click 0.5, 0.3" or "hotkey LeftCmd+Space"


def _make_vision_model():
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "El loop visual requiere GOOGLE_API_KEY (Gemini). "
            "Configura la variable en .env o exporta antes de arrancar."
        )
    # Lazy import to avoid pulling google deps at module load.
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=VISION_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=0.1,
        max_output_tokens=400,
    )


def _strip_json(raw: str) -> str:
    s = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    if fence:
        s = fence.group(1).strip()
    return s


def _format_history(history: list[HistoryItem]) -> str:
    if not history:
        return "(sin historial)"
    return "\n".join(
        f"{i+1}. {h.action_summary} — {h.reasoning}" for i, h in enumerate(history[-4:])
    )


def next_action(
    goal: str,
    screenshot_png_b64: str,
    history: list[HistoryItem],
    os_hint: str | None = None,
) -> LoopDecision:
    model = _make_vision_model()
    os_hint = os_hint or platform.system()
    user_text = (
        f"Objetivo: {goal}\n"
        f"Sistema operativo: {os_hint}\n"
        f"Historial reciente:\n{_format_history(history)}\n"
        "Responde solo con el JSON descrito en las reglas."
    )
    msg = model.invoke(
        [
            SystemMessage(content=_SYSTEM),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": f"data:image/png;base64,{screenshot_png_b64}",
                    },
                ]
            ),
        ]
    )
    raw = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
    cleaned = _strip_json(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Actor returned non-JSON: {e}: {cleaned[:200]}") from e
    return LoopDecision.model_validate(data)
```

- [ ] **Step 2: Sanity import check (no API call yet)**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -c "from helpdesk_app.vision_loop.actor import next_action, HistoryItem; print('ok')"`

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add helpdesk_app/vision_loop/actor.py
git commit -m "feat(vision_loop): vision actor calling Gemini for one action per turn"
```

---

## Task 9: Vision loop — `events.py` (run registry + pub/sub)

**Files:**
- Create: `helpdesk_app/vision_loop/events.py`

- [ ] **Step 1: Implement event bus and run registry**

```python
# helpdesk_app/vision_loop/events.py
"""Registro de runs activos + cola de eventos para SSE y confirmaciones humanas."""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunState:
    run_id: str
    goal: str
    started_at: float = field(default_factory=time.time)
    abort_flag: threading.Event = field(default_factory=threading.Event)
    confirm_queue: "queue.Queue[bool]" = field(default_factory=queue.Queue)
    event_queue: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    finished: bool = False


_RUNS: dict[str, RunState] = {}
_LOCK = threading.Lock()


def create_run(goal: str) -> RunState:
    rid = uuid.uuid4().hex[:12]
    state = RunState(run_id=rid, goal=goal)
    with _LOCK:
        _RUNS[rid] = state
    return state


def get_run(run_id: str) -> RunState | None:
    with _LOCK:
        return _RUNS.get(run_id)


def finish_run(run_id: str) -> None:
    with _LOCK:
        st = _RUNS.get(run_id)
        if st:
            st.finished = True


def cleanup_old_runs(max_age_s: float = 600.0) -> None:
    cutoff = time.time() - max_age_s
    with _LOCK:
        stale = [k for k, v in _RUNS.items() if v.finished and v.started_at < cutoff]
        for k in stale:
            _RUNS.pop(k, None)


def emit(state: RunState, event_type: str, payload: dict) -> None:
    state.event_queue.put({"type": event_type, "ts": time.time(), **payload})


def request_confirm(state: RunState, payload: dict, timeout_s: float = 60.0) -> bool:
    """Block until UI POSTs a confirmation or timeout."""
    emit(state, "confirm_required", payload)
    try:
        return state.confirm_queue.get(timeout=timeout_s)
    except queue.Empty:
        return False
```

- [ ] **Step 2: Sanity check**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -c "from helpdesk_app.vision_loop.events import create_run, emit; s = create_run('test'); emit(s,'x',{}); print(s.event_queue.get_nowait())"`

Expected: prints a dict with `type='x'`.

- [ ] **Step 3: Commit**

```bash
git add helpdesk_app/vision_loop/events.py
git commit -m "feat(vision_loop): run registry + pub/sub event bus"
```

---

## Task 10: Vision loop — `loop.py` state machine (with fake actor seam)

**Files:**
- Create: `helpdesk_app/vision_loop/loop.py`
- Test: `tests/test_vision_loop_state.py` (create)

- [ ] **Step 1: Write failing test using injected fakes**

```python
# tests/test_vision_loop_state.py
from helpdesk_app.vision_loop import loop as loop_mod
from helpdesk_app.vision_loop.events import create_run
from helpdesk_app.vision_loop.schema import LoopDecision


class FakeCapture:
    def __init__(self):
        self.png_b64 = "ZmFrZQ=="
        self.thumb_b64 = "ZmFrZQ=="
        self.width = 100
        self.height = 100


def test_loop_stops_on_done_immediately():
    state = create_run("dummy")
    decisions = iter([LoopDecision(reasoning="ya estaba", done=True)])

    def fake_capture():
        return FakeCapture()

    def fake_next_action(goal, png, history, os_hint=None):
        return next(decisions)

    executed = []

    def fake_execute(action):
        executed.append(action)

    outcome = loop_mod.run_loop(
        state,
        max_steps=5,
        total_timeout_s=10,
        capture_fn=fake_capture,
        actor_fn=fake_next_action,
        execute_fn=fake_execute,
        sleep_fn=lambda s: None,
    )
    assert outcome.status == "done"
    assert executed == []


def test_loop_executes_then_done():
    state = create_run("dummy")
    decisions = iter([
        LoopDecision(
            reasoning="primer paso",
            action={"type": "hotkey", "keys": ["LeftCmd", "Space"], "delayMs": 100},
        ),
        LoopDecision(reasoning="hecho", done=True),
    ])

    def fake_capture():
        return FakeCapture()

    def fake_next_action(goal, png, history, os_hint=None):
        return next(decisions)

    executed = []

    def fake_execute(action):
        executed.append(action.type)

    outcome = loop_mod.run_loop(
        state, max_steps=5, total_timeout_s=10,
        capture_fn=fake_capture, actor_fn=fake_next_action,
        execute_fn=fake_execute, sleep_fn=lambda s: None,
    )
    assert outcome.status == "done"
    assert executed == ["hotkey"]


def test_loop_stops_on_max_steps():
    state = create_run("dummy")

    def decision_factory():
        while True:
            yield LoopDecision(
                reasoning="seguir",
                action={"type": "wait", "delayMs": 1},
            )

    gen = decision_factory()

    def fake_capture():
        return FakeCapture()

    def fake_next_action(goal, png, history, os_hint=None):
        return next(gen)

    def fake_execute(action):
        pass

    outcome = loop_mod.run_loop(
        state, max_steps=3, total_timeout_s=10,
        capture_fn=fake_capture, actor_fn=fake_next_action,
        execute_fn=fake_execute, sleep_fn=lambda s: None,
    )
    assert outcome.status == "max_steps"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -m pytest tests/test_vision_loop_state.py -v`

Expected: FAIL — module `helpdesk_app.vision_loop.loop` does not exist.

- [ ] **Step 3: Implement loop with injectable seams**

```python
# helpdesk_app/vision_loop/loop.py
"""Loop visual agéntico: state machine."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from helpdesk_app.config import BASE_DIR, desktop_py_exec_enabled
from helpdesk_app.vision_loop import events as ev
from helpdesk_app.vision_loop.actor import HistoryItem, next_action as real_next_action
from helpdesk_app.vision_loop.executor import ExecutionError, run as real_execute
from helpdesk_app.vision_loop.schema import LoopDecision
from helpdesk_app.vision_loop.screen import Capture, capture as real_capture


@dataclass
class LoopOutcome:
    status: str           # done | fail | needs_user | max_steps | timeout | aborted | user_canceled | gate_disabled
    reason: str = ""
    steps: int = 0


_AUDIT_PATH = Path(BASE_DIR) / "data" / "automation_log.jsonl"


def _audit(run_id: str, payload: dict) -> None:
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": run_id, "ts": time.time(), **payload}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _summarize_action(d: LoopDecision) -> str:
    if d.action is None:
        return "(terminal)"
    a = d.action
    if a.type == "hotkey":
        return "hotkey " + "+".join(a.keys)
    if a.type == "move":
        return f"move {a.x:.2f},{a.y:.2f}"
    if a.type == "click":
        return f"click {a.button}"
    if a.type == "type":
        txt = (a.text or "")[:24]
        return f"type {txt!r}"
    if a.type == "wait":
        return f"wait {a.delayMs}ms"
    return a.type


def run_loop(
    state: ev.RunState,
    *,
    max_steps: int = 20,
    total_timeout_s: float = 90.0,
    capture_fn: Callable[[], Capture] = real_capture,
    actor_fn: Callable[..., LoopDecision] = real_next_action,
    execute_fn: Callable[..., None] = real_execute,
    sleep_fn: Callable[[float], None] = time.sleep,
    confirm_fn: Callable[[ev.RunState, dict], bool] = ev.request_confirm,
) -> LoopOutcome:
    if not desktop_py_exec_enabled():
        outcome = LoopOutcome(status="gate_disabled", reason="HELPDESK_DESKTOP_PY_EXEC no está activo")
        ev.emit(state, "fail", {"reason": outcome.reason})
        ev.finish_run(state.run_id)
        return outcome

    history: list[HistoryItem] = []
    t0 = time.time()
    step_n = 0
    try:
        for step_n in range(1, max_steps + 1):
            if state.abort_flag.is_set():
                outcome = LoopOutcome(status="aborted", reason="user_abort", steps=step_n - 1)
                ev.emit(state, "aborted", {"reason": outcome.reason})
                return outcome
            if time.time() - t0 > total_timeout_s:
                outcome = LoopOutcome(status="timeout", steps=step_n - 1)
                ev.emit(state, "fail", {"reason": "timeout"})
                return outcome

            cap = capture_fn()
            try:
                decision = actor_fn(state.goal, cap.png_b64, history)
            except Exception as e:
                outcome = LoopOutcome(status="fail", reason=f"actor_error: {e}", steps=step_n - 1)
                ev.emit(state, "fail", {"reason": outcome.reason})
                _audit(state.run_id, {"event": "actor_error", "error": str(e)})
                return outcome

            summary = _summarize_action(decision)
            ev.emit(state, "step", {
                "n": step_n,
                "max": max_steps,
                "thumb_b64": cap.thumb_b64,
                "reasoning": decision.reasoning,
                "action": decision.action.model_dump() if decision.action else None,
                "summary": summary,
                "sensitive": bool(decision.action and decision.action.sensitive),
            })
            _audit(state.run_id, {"event": "step", "n": step_n, "summary": summary,
                                  "reasoning": decision.reasoning,
                                  "action": decision.action.model_dump() if decision.action else None})

            if decision.done:
                ev.emit(state, "done", {"reason": decision.reason or "objetivo cumplido"})
                return LoopOutcome(status="done", reason=decision.reason, steps=step_n)
            if decision.fail:
                ev.emit(state, "fail", {"reason": decision.reason or "actor:fail"})
                return LoopOutcome(status="fail", reason=decision.reason, steps=step_n)
            if decision.needs_user:
                ev.emit(state, "needs_user", {"reason": decision.reason or "se requiere usuario"})
                return LoopOutcome(status="needs_user", reason=decision.reason, steps=step_n)

            if decision.action and decision.action.sensitive:
                approved = confirm_fn(state, {
                    "n": step_n,
                    "full_b64": cap.png_b64,
                    "summary": summary,
                    "reasoning": decision.reasoning,
                    "action": decision.action.model_dump(),
                })
                if not approved:
                    outcome = LoopOutcome(status="user_canceled", reason="rechazada por usuario", steps=step_n)
                    ev.emit(state, "aborted", {"reason": outcome.reason})
                    return outcome

            try:
                execute_fn(decision.action)
            except ExecutionError as e:
                outcome = LoopOutcome(status="fail", reason=f"exec_error: {e}", steps=step_n)
                ev.emit(state, "fail", {"reason": outcome.reason})
                _audit(state.run_id, {"event": "exec_error", "error": str(e)})
                return outcome

            history.append(HistoryItem(reasoning=decision.reasoning, action_summary=summary))
            sleep_fn(0.05)

        outcome = LoopOutcome(status="max_steps", steps=max_steps)
        ev.emit(state, "fail", {"reason": "max_steps"})
        return outcome
    finally:
        ev.finish_run(state.run_id)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 -m pytest tests/test_vision_loop_state.py -v`

Expected: 3 PASS. (Note: `HELPDESK_DESKTOP_PY_EXEC=1` is required because the loop refuses without the gate.)

- [ ] **Step 5: Commit**

```bash
git add helpdesk_app/vision_loop/loop.py tests/test_vision_loop_state.py
git commit -m "feat(vision_loop): state machine with topes, abort, confirm seams"
```

---

## Task 11: LangGraph tool — `ejecutar_tarea_escritorio`

**Files:**
- Modify: `helpdesk_app/tools.py`

- [ ] **Step 1: Update `buscar_en_base_de_conocimiento` to expose `top_k` + `diversidad`**

Replace the existing `buscar_en_base_de_conocimiento` (lines 59–72) with:

```python
@tool
def buscar_en_base_de_conocimiento(consulta: str, top_k: int = 4, diversidad: bool = False) -> str:
    """Busca en la KB (RAG). Úsalo en cuanto haya un caso concreto. Parámetros:
    - top_k: número de fragmentos (1-8 razonable, por defecto 4).
    - diversidad: si True usa MMR (resultados más diversos)."""
    k = max(1, min(int(top_k), 10))
    docs = buscar_contexto(consulta, k=k, mmr=bool(diversidad))
    if not docs:
        return "No se encontraron fragmentos relevantes en la base de conocimiento."
    bloques: list[str] = []
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source", "")
        preview = (d.page_content or "").strip().replace("\n", " ")[:240]
        chat_trace.add_kb_source(str(src), preview)
        bloques.append(f"--- Fragmento {i} ({src}) ---\n{d.page_content.strip()}")
    return "\n\n".join(bloques)
```

- [ ] **Step 2: Add `ejecutar_tarea_escritorio` tool**

Append before `def all_tools():` (around line 241):

```python
@tool
def ejecutar_tarea_escritorio(goal: str) -> str:
    """Ejecuta un objetivo paso a paso en el escritorio mirando capturas de pantalla.
    Loop: captura → razona → UNA acción → verifica → repite (máx 20 pasos, 90s totales).
    Pide aprobación humana en cada paso marcado sensible. Úsalo SOLO si el usuario
    pidió explícitamente que el sistema haga algo en su equipo (p. ej. "envíalo en mi Outlook",
    "abre Ajustes y cambia X"). Devuelve resumen del resultado, no inventes pasos."""
    from helpdesk_app.vision_loop import events as ev
    from helpdesk_app.vision_loop.loop import run_loop

    g = (goal or "").strip()
    if len(g) < 4:
        return json.dumps({"status": "fail", "reason": "Objetivo demasiado corto."}, ensure_ascii=False)

    state = ev.create_run(g)
    chat_trace.add_kb_source("[automation]", f"run_id={state.run_id} goal={g[:120]}")
    outcome = run_loop(state)
    return json.dumps({
        "run_id": state.run_id,
        "status": outcome.status,
        "reason": outcome.reason,
        "steps": outcome.steps,
    }, ensure_ascii=False)
```

- [ ] **Step 3: Register the new tool**

In `all_tools()` (around line 242–252), append `ejecutar_tarea_escritorio` to the list:

```python
def all_tools():
    return [
        buscar_en_base_de_conocimiento,
        buscar_en_web,
        buscar_casos_resueltos_previos,
        crear_ticket_de_servicio,
        actualizar_ticket_de_servicio,
        registrar_ticket_resuelto,
        escalar_a_especialista,
        preparar_plan_escritorio,
        guardar_snippet_en_kb,
        ejecutar_tarea_escritorio,
    ]
```

- [ ] **Step 4: Sanity import**

Run: `cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent && ../.venv/bin/python3 -c "from helpdesk_app.tools import all_tools; print([t.name for t in all_tools()])"`

Expected: prints list including `'ejecutar_tarea_escritorio'`.

- [ ] **Step 5: Commit**

```bash
git add helpdesk_app/tools.py
git commit -m "feat(tools): expose vision-loop tool + top_k/mmr on KB search"
```

---

## Task 12: FastAPI — SSE stream + abort + confirm endpoints

**Files:**
- Modify: `helpdesk_app/main.py`

- [ ] **Step 1: Add endpoints**

At the bottom of `helpdesk_app/main.py`, before any final `if __name__ ...` (there isn't one currently, so simply append at end), add:

```python
from fastapi.responses import StreamingResponse
from helpdesk_app.vision_loop import events as vl_events


@app.get("/api/desktop/loop/stream/{run_id}")
def loop_stream(run_id: str):
    state = vl_events.get_run(run_id)
    if state is None:
        raise HTTPException(404, "run_id desconocido")

    def gen():
        # Initial hello so the client knows the connection is alive.
        yield f"event: hello\ndata: {json.dumps({'run_id': run_id})}\n\n"
        while True:
            try:
                msg = state.event_queue.get(timeout=1.0)
            except Exception:
                if state.finished and state.event_queue.empty():
                    yield "event: closed\ndata: {}\n\n"
                    return
                # keepalive
                yield ": keepalive\n\n"
                continue
            yield f"event: {msg['type']}\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg["type"] in ("done", "fail", "aborted") and state.event_queue.empty():
                yield "event: closed\ndata: {}\n\n"
                return

    return StreamingResponse(gen(), media_type="text/event-stream")


class _AbortBody(BaseModel):
    run_id: str


@app.post("/api/desktop/loop/abort")
def loop_abort(body: _AbortBody):
    state = vl_events.get_run(body.run_id)
    if state is None:
        raise HTTPException(404, "run_id desconocido")
    state.abort_flag.set()
    return {"ok": True}


class _ConfirmBody(BaseModel):
    run_id: str
    approved: bool


@app.post("/api/desktop/loop/confirm")
def loop_confirm(body: _ConfirmBody):
    state = vl_events.get_run(body.run_id)
    if state is None:
        raise HTTPException(404, "run_id desconocido")
    state.confirm_queue.put(bool(body.approved))
    return {"ok": True}


@app.get("/api/desktop/loop/runs")
def loop_runs():
    vl_events.cleanup_old_runs()
    return {"active": []}  # placeholder; full registry exposure not needed for the demo
```

- [ ] **Step 2: Smoke-boot server and curl an unknown run**

In one shell:

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 HELPDESK_PORT=8788 ../.venv/bin/python3 run.py
```

In another:

```bash
curl -i http://127.0.0.1:8788/api/desktop/loop/stream/nonexistent
```

Expected: HTTP 404 with `run_id desconocido`. Kill the server.

- [ ] **Step 3: Commit**

```bash
git add helpdesk_app/main.py
git commit -m "feat(api): SSE stream + abort + confirm endpoints for vision loop"
```

---

## Task 13: UI — live automation panel + confirm modal

**Files:**
- Modify: `helpdesk_app/static/app.js` (locate the file actually used; check `helpdesk_app/static/` and `helpdesk_app/templates/index.html` for `<script src=...>`)
- Modify: `helpdesk_app/static/styles.css` (same caveat)

- [ ] **Step 1: Locate the right files**

Run:

```bash
grep -R "script" /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent/helpdesk_app/templates/index.html
ls /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent/helpdesk_app/static/
```

Identify the JS file currently driving the chat UI (likely `app.js` or `chat.js`) and the CSS. Use those exact paths in the steps below.

- [ ] **Step 2: Add panel HTML**

In `helpdesk_app/templates/index.html`, just before `</body>`, append:

```html
<aside id="automationPanel" hidden>
  <header>
    <span id="apStatus">Automatización en vivo</span>
    <button id="apAbort" type="button">Abortar</button>
  </header>
  <div id="apThumbWrap"><img id="apThumb" alt="captura" /></div>
  <div id="apStepInfo"></div>
  <ol id="apHistory"></ol>
</aside>

<div id="apConfirmModal" hidden>
  <div class="ap-modal-card">
    <h3>Confirmar paso sensible</h3>
    <img id="apConfirmImg" alt="captura completa" />
    <pre id="apConfirmAction"></pre>
    <div class="ap-modal-buttons">
      <button id="apConfirmApprove" type="button">Aprobar</button>
      <button id="apConfirmCancel" type="button">Cancelar</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add CSS**

Append to the CSS file located in Step 1:

```css
#automationPanel { position: fixed; right: 16px; bottom: 16px; width: 360px;
  background: #111; color: #eee; padding: 12px; border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0,0,0,.4); font-family: system-ui, sans-serif; z-index: 9999; }
#automationPanel header { display: flex; justify-content: space-between; align-items: center; }
#automationPanel #apAbort { background: #c0392b; color: white; border: 0; padding: 4px 10px; border-radius: 4px; cursor: pointer; }
#automationPanel #apThumb { width: 100%; border-radius: 4px; margin: 8px 0; }
#automationPanel ol { font-size: 12px; max-height: 140px; overflow-y: auto; padding-left: 18px; }
#apConfirmModal { position: fixed; inset: 0; background: rgba(0,0,0,.7); display: flex; align-items: center; justify-content: center; z-index: 10000; }
#apConfirmModal .ap-modal-card { background: #fff; padding: 16px; border-radius: 8px; max-width: 720px; width: 90%; max-height: 80vh; overflow: auto; }
#apConfirmModal img { width: 100%; border: 1px solid #ddd; }
#apConfirmModal pre { background: #f4f4f4; padding: 8px; font-size: 12px; white-space: pre-wrap; }
#apConfirmModal .ap-modal-buttons { display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px; }
#apConfirmModal #apConfirmApprove { background: #2ecc71; color: #fff; border: 0; padding: 6px 14px; border-radius: 4px; cursor: pointer; }
#apConfirmModal #apConfirmCancel { background: #95a5a6; color: #fff; border: 0; padding: 6px 14px; border-radius: 4px; cursor: pointer; }
```

- [ ] **Step 4: Add JS to drive SSE + abort + confirm**

Append to the JS file located in Step 1:

```js
(function () {
  const panel = document.getElementById('automationPanel');
  const apThumb = document.getElementById('apThumb');
  const apStepInfo = document.getElementById('apStepInfo');
  const apHistory = document.getElementById('apHistory');
  const apStatus = document.getElementById('apStatus');
  const apAbort = document.getElementById('apAbort');
  const confirmModal = document.getElementById('apConfirmModal');
  const confirmImg = document.getElementById('apConfirmImg');
  const confirmAction = document.getElementById('apConfirmAction');
  const confirmApprove = document.getElementById('apConfirmApprove');
  const confirmCancel = document.getElementById('apConfirmCancel');
  let currentRun = null;
  let es = null;

  function show() { panel.hidden = false; }
  function hide() { panel.hidden = true; apHistory.innerHTML = ''; apStepInfo.textContent = ''; }

  async function postJSON(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  }

  function attachStream(runId) {
    currentRun = runId;
    show();
    apStatus.textContent = `Automatización · run ${runId}`;
    if (es) { es.close(); }
    es = new EventSource(`/api/desktop/loop/stream/${runId}`);
    es.addEventListener('step', (e) => {
      const d = JSON.parse(e.data);
      apThumb.src = 'data:image/png;base64,' + d.thumb_b64;
      apStepInfo.textContent = `Paso ${d.n}/${d.max} · ${d.summary} — ${d.reasoning}`;
      const li = document.createElement('li');
      li.textContent = `${d.n}. ${d.summary} — ${d.reasoning}`;
      apHistory.appendChild(li);
    });
    es.addEventListener('confirm_required', (e) => {
      const d = JSON.parse(e.data);
      confirmImg.src = 'data:image/png;base64,' + d.full_b64;
      confirmAction.textContent = `Paso ${d.n}: ${d.summary}\n${d.reasoning}\n\n${JSON.stringify(d.action, null, 2)}`;
      confirmModal.hidden = false;
      confirmApprove.onclick = () => { postJSON('/api/desktop/loop/confirm', { run_id: currentRun, approved: true }); confirmModal.hidden = true; };
      confirmCancel.onclick = () => { postJSON('/api/desktop/loop/confirm', { run_id: currentRun, approved: false }); confirmModal.hidden = true; };
    });
    es.addEventListener('done', () => { apStatus.textContent = 'Hecho.'; });
    es.addEventListener('fail', (e) => { const d = JSON.parse(e.data); apStatus.textContent = 'Fallo: ' + (d.reason || ''); });
    es.addEventListener('aborted', () => { apStatus.textContent = 'Abortado.'; });
    es.addEventListener('closed', () => { es.close(); setTimeout(hide, 4000); });
  }

  apAbort.addEventListener('click', () => {
    if (!currentRun) return;
    postJSON('/api/desktop/loop/abort', { run_id: currentRun });
  });

  // Expose a global helper: when the chat sees a tool result with run_id, call this.
  window.helpdeskAttachAutomation = attachStream;
})();
```

- [ ] **Step 5: Hook into the chat tool-result handler**

Find where the existing chat JS handles tool results (search for the tool name `preparar_plan_escritorio` in `helpdesk_app/static/`). Add a parallel branch that, when a tool result contains `ejecutar_tarea_escritorio` with a `run_id` field, calls `window.helpdeskAttachAutomation(run_id)`. The exact location depends on the existing handler; mirror its style.

Run: open the UI in a browser, send a message like "abre Spotlight tú mismo" with the gate env on; the panel should appear when the tool fires.

- [ ] **Step 6: Commit**

```bash
git add helpdesk_app/templates/index.html helpdesk_app/static/
git commit -m "feat(ui): live automation panel with SSE + confirm modal"
```

---

## Task 14: Demo checklist + macOS permissions docs

**Files:**
- Create: `docs/demo-checklist.md`
- Modify: `helpdesk_agent/README.md` (or create if missing)

- [ ] **Step 1: Write the demo checklist**

```markdown
# Demo Checklist — Mesa de ayuda TI (entrega final)

## 1 hora antes
- [ ] Vaciar `data/automation_log.jsonl` (mover a `.bak`).
- [ ] `HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 run.py` y abrir Electron.
- [ ] **Smoke test del loop**: "abre Spotlight y escribe calculadora" → debe verse cursor moverse, captura cambiar y al final Spotlight con "calculadora".
- [ ] Verificar permisos macOS: System Settings → Privacy & Security → Accesibilidad y Grabación de pantalla incluyen Python/Electron.

## Demo Outlook web (caso estrella)
- [ ] Abrir Outlook web manualmente en Safari/Chrome, login hecho, bandeja vacía de drafts.
- [ ] En el chat: "envíame un correo a <destino> con asunto 'Demo' y cuerpo corto. Hazlo tú en mi Outlook web."
- [ ] Verificar: panel aparece, cursor se mueve, captura va cambiando, modal de confirmación al pulsar **Enviar**.
- [ ] **Plan B**: si Outlook pide login o cambia el layout — el actor debe devolver `needs_user` (la UI lo mostrará). Comentarlo como característica.

## Demo RAG rápido
- [ ] Pregunta: "mi VPN no conecta, qué hago" → debe responder en < 3s sin tocar la web.
- [ ] Pregunta: "busca en internet la versión última de Cisco AnyConnect" → debe avisar antes de ir a web.

## Cierre
- [ ] Mostrar `data/automation_log.jsonl` (transparencia: cada paso queda registrado).
- [ ] Mostrar `data/tickets.sqlite3` con el ticket creado durante la sesión.
```

- [ ] **Step 2: Add macOS permissions section to README**

If `helpdesk_agent/README.md` doesn't exist, create with this minimal content; else append:

```markdown
## Permisos macOS para el loop visual

El loop agéntico necesita:

1. **Accesibilidad** (mover ratón / teclado): Ajustes del Sistema → Privacidad y seguridad → Accesibilidad. Añadir Python (o el binario que ejecute uvicorn) **y** Electron (si usas el cliente).
2. **Grabación de pantalla** (capturas): misma ruta, sección "Grabación de pantalla". Añadir Python y Electron.
3. Reiniciar el proceso después de conceder permisos.

Variable de entorno requerida para activar la ejecución:

```bash
export HELPDESK_DESKTOP_PY_EXEC=1
```

Sin ella, el agente devuelve `gate_disabled` y nunca toca el ratón.
```

- [ ] **Step 3: Commit**

```bash
git add docs/demo-checklist.md helpdesk_agent/README.md
git commit -m "docs: demo checklist + macOS permissions notes"
```

---

## Task 15: End-to-end smoke (manual, before declaring done)

- [ ] **Step 1: Full stack boot**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 run.py
```

- [ ] **Step 2: Smoke prompt**

Open the UI. Type:

> Abre Spotlight tú mismo y busca "calculadora".

Expected: chat triggers `ejecutar_tarea_escritorio`, panel appears, you see ~3-5 steps (hotkey LeftCmd+Space, wait, type "calculadora", wait, done), cursor visible, ending status "Hecho".

- [ ] **Step 3: RAG smoke**

Type:

> Mi VPN no conecta, ¿qué hago?

Expected: response in < 3s, contains `## Plan de acción`, **no** mention of web sources unless the user asked. Server logs show only KB lookup, not web.

- [ ] **Step 4: Run all unit tests**

```bash
cd /Users/jacobopavaquintero/IA_WORKSHOPS/helpdesk_agent
HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Mark task complete**

If everything passes, the feature is shippable for the demo. Update `data/automation_log.jsonl` review and confirm no surprises in audit log.

---

## Self-review notes

- **Spec coverage:** §3 architecture (Tasks 5–13), §4 vision loop state machine (Task 10), §4.2 schema (Task 5), §4.3 prompt (Task 8), §4.4 topes/security (Task 10 + gate check), §5 RAG (Tasks 1–4), §6 UI (Tasks 12–13), §8 audit log (Task 10 `_audit`), §9 testing/demo (Tasks 14–15). All covered.
- **Placeholders:** every step has concrete code or a concrete command.
- **Type consistency:** `LoopDecision` (Task 5) used identically in Tasks 8, 10, 11; `DesktopAction` reused from existing `desktop_plan.py`; `RunState` from Task 9 used in 10–12.
- **Not a git repo:** noted in Task 1, Step 5 — engineer should `git init` first or skip commit steps.
- **Vision loop refuses without the env gate:** captured in Task 10 (the gate check happens before any capture). Tests pass the env var; demo too.
