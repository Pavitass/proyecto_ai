import json
import os
import time as _time
import uuid as _uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field, field_validator

from helpdesk_app import agent_trace as _agent_trace
from helpdesk_app import chat_context as chat_ctx
from helpdesk_app import chat_trace
from helpdesk_app import db
from helpdesk_app.config import (
    desktop_force_human_ack,
    desktop_py_exec_enabled,
    vision_capabilities_payload,
)
from helpdesk_app.desktop_exec_py import run_pyautogui_action
from helpdesk_app.desktop_plan import DesktopAction, DesktopPlanError, generate_desktop_plan
from helpdesk_app.graph import build_app_graph
from helpdesk_app.interactive_block import (
    ensure_widget_if_info_request,
    parse_helpdesk_ui_block,
    strip_helpdesk_ui_block,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Mesa de ayuda TI", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_app_graph()
    return _graph


@app.on_event("startup")
def startup():
    db.init_db()
    from helpdesk_app import rag
    rag.warmup()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    port = int(os.getenv("HELPDESK_PORT", "8787"))
    base = f"http://127.0.0.1:{port}"
    return templates.TemplateResponse(
        request,
        "index.html",
        {"helpdesk_base_url": base, "helpdesk_port": port},
    )


@app.get("/widget", response_class=HTMLResponse)
def widget_page(request: Request):
    port = int(os.getenv("HELPDESK_PORT", "8787"))
    base = f"http://127.0.0.1:{port}"
    return templates.TemplateResponse(
        request,
        "widget.html",
        {"helpdesk_base_url": base, "helpdesk_port": port},
    )


class InteractionBlock(BaseModel):
    type: str = Field(..., min_length=2, max_length=64)
    payload: dict = Field(default_factory=dict)


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    thread_id: str = Field(..., min_length=4, max_length=128)
    screenshots: list[str] = Field(default_factory=list)
    interaction: InteractionBlock | None = None
    client_os: str | None = Field(default=None, max_length=32)
    turn_id: str | None = Field(default=None, max_length=64)

    @field_validator("screenshots", mode="before")
    @classmethod
    def limit_screenshots(cls, v):
        if not v:
            return []
        if not isinstance(v, list):
            return []
        return [str(x) for x in v[:2]]


class SourceOut(BaseModel):
    kind: str = "kb"
    label: str = ""
    detail: str = ""
    url: str = ""


class ToolCallOut(BaseModel):
    name: str = ""
    args_preview: str = ""


class ChatOut(BaseModel):
    reply: str
    thread_id: str
    vision_used: bool = False
    desktop_plan: dict | None = None
    desktop_run: dict | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    tool_calls_used: list[ToolCallOut] = Field(default_factory=list)
    web_search_used: bool = False
    turn_id: str | None = None
    helpdesk_ui: dict | None = None  # parsed `helpdesk-ui` widget block


class DesktopPlanIn(BaseModel):
    goal: str = Field(..., min_length=4, max_length=2000)
    screenshots: list[str] = Field(default_factory=list)
    client_os: str | None = Field(default=None, max_length=32)

    @field_validator("screenshots", mode="before")
    @classmethod
    def one_shot(cls, v):
        if not v:
            return []
        if not isinstance(v, list):
            return []
        return [str(x) for x in v[:1]]


@app.get("/api/capabilities")
def capabilities():
    return vision_capabilities_payload()


class DesktopExecIn(BaseModel):
    action: dict
    human_ack: bool = False


def _client_is_loopback(request: Request) -> bool:
    c = request.client
    host = (c.host if c else "").strip().lower()
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    if host.startswith("::ffff:") and host.endswith("127.0.0.1"):
        return True
    return False


@app.post("/api/desktop/plan")
def desktop_plan(body: DesktopPlanIn):
    try:
        return generate_desktop_plan(
            body.goal.strip(),
            body.screenshots or None,
            client_os=body.client_os,
        )
    except DesktopPlanError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/desktop/exec")
def desktop_exec(body: DesktopExecIn, request: Request):
    """Ejecuta un paso con PyAutoGUI en la máquina del servidor (solo localhost + env)."""
    if not desktop_py_exec_enabled():
        raise HTTPException(
            status_code=403,
            detail="PyAutoGUI desactivado. Define HELPDESK_DESKTOP_PY_EXEC=1 en el entorno del servidor.",
        )
    if not _client_is_loopback(request):
        raise HTTPException(
            status_code=403,
            detail="Solo desde localhost: el ratón/teclado se mueven en la máquina donde corre uvicorn.",
        )
    try:
        action = DesktopAction.model_validate(body.action)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Acción inválida: {e}") from e

    need_ack = bool(action.sensitive or desktop_force_human_ack())
    if need_ack and not body.human_ack:
        raise HTTPException(
            status_code=400,
            detail="Human-in-the-loop: envía human_ack=true tras confirmar en la interfaz.",
        )

    err = run_pyautogui_action(action.model_dump())
    if err:
        raise HTTPException(status_code=500, detail=err)
    return {"ok": True}


def _tool_message_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _extract_desktop_run(msgs: list) -> dict | None:
    for m in reversed(msgs):
        if not isinstance(m, ToolMessage):
            continue
        if getattr(m, "name", None) != "ejecutar_tarea_escritorio":
            continue
        raw = _tool_message_content(m.content).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("run_id"):
            return {
                "run_id": data["run_id"],
                "status": data.get("status"),
                "steps": data.get("steps"),
            }
    return None


def _extract_desktop_plan(msgs: list) -> dict | None:
    for m in reversed(msgs):
        if not isinstance(m, ToolMessage):
            continue
        if getattr(m, "name", None) != "preparar_plan_escritorio":
            continue
        raw = _tool_message_content(m.content).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("error"):
            return None
        if "actions" not in data:
            continue
        return {
            "rationale": str(data.get("rationale") or ""),
            "actions": data.get("actions") or [],
        }
    return None


def _dedupe_tool_calls_preserve(rows: list[ToolCallOut]) -> list[ToolCallOut]:
    seen: set[tuple[str, str]] = set()
    out: list[ToolCallOut] = []
    for r in rows:
        key = (r.name, r.args_preview)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _extract_tool_trace_last_turn(msgs: list) -> list[ToolCallOut]:
    last_human = -1
    for i, m in enumerate(msgs):
        if isinstance(m, HumanMessage):
            last_human = i
    out: list[ToolCallOut] = []
    if last_human < 0:
        return out
    for m in msgs[last_human + 1 :]:
        if not isinstance(m, AIMessage) or not m.tool_calls:
            continue
        for tc in m.tool_calls:
            name = str(tc.get("name") or "")
            args = tc.get("args") or {}
            try:
                preview = json.dumps(args, ensure_ascii=False)
            except TypeError:
                preview = str(args)
            if len(preview) > 420:
                preview = preview[:420] + "…"
            out.append(ToolCallOut(name=name, args_preview=preview))
    return _dedupe_tool_calls_preserve(out)


def _sources_from_trace(snap: dict) -> tuple[list[SourceOut], bool]:
    web_used = bool((snap.get("web_sources") or []))
    seen_kb: set[str] = set()
    sources: list[SourceOut] = []
    for x in snap.get("kb_sources") or []:
        src = (x.get("source") or "").strip()
        if not src or src in seen_kb:
            continue
        seen_kb.add(src)
        sources.append(
            SourceOut(kind="kb", label=src, detail=(x.get("preview") or "")[:500], url="")
        )
    for x in snap.get("web_sources") or []:
        sources.append(
            SourceOut(
                kind="web",
                label=(x.get("title") or x.get("url") or "Web")[:220],
                detail=(x.get("snippet") or "")[:520],
                url=(x.get("url") or "")[:900],
            )
        )
    return sources, web_used


@app.post("/api/chat", response_model=ChatOut)
def chat(body: ChatIn):
    _turn_id = (body.turn_id or "").strip() or _uuid.uuid4().hex[:12]
    _agent_trace.begin_turn(body.thread_id, _turn_id)
    _t0 = _time.time()
    _agent_trace.emit(_turn_id, "phase", {"phase": "analyzing"})
    try:
        try:
            graph = get_graph()
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

        vision_used = bool(body.screenshots)
        full_message = body.message.strip()
        if body.screenshots:
            from helpdesk_app import vision

            try:
                summary = vision.describe_screenshots(body.message, body.screenshots)
            except RuntimeError as e:
                raise HTTPException(status_code=503, detail=str(e)) from e
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            full_message = (
                "### Análisis automático de la(s) captura(s) (visión)\n\n"
                + summary
                + "\n\n### Mensaje del usuario\n\n"
                + body.message.strip()
            )

        if body.interaction:
            ix_blob = json.dumps(
                body.interaction.model_dump(), ensure_ascii=False, indent=2
            )
            full_message = (
                "[Panel en vivo — el usuario usó la interfaz interactiva (bottom sheet). "
                "Interpreta el JSON: si `type` es `step_failed`, desglosa **sub-pasos** bajo el paso indicado "
                "y actualiza herramientas/ticket si aplica; si es `kanban_update` o `slider_values`, "
                "incorpora el estado en tu plan y responde de forma breve. "
                "Si `type` es `desktop_plan_feedback`, el usuario indica por **cada paso** del plan de escritorio "
                "si quedó **hecho**, **pendiente** o **falló**: prioriza sub-pasos manuales, revisa KB o web, "
                "regenera `preparar_plan_escritorio` solo si aporta, y actualiza el ticket.]\n"
                f"```json\n{ix_blob}\n```\n\n"
                + full_message
            )

        # inject step status snapshot for the LLM
        _steps_block = _step_state.render_status_block(body.thread_id)
        _user_text_with_state = (_steps_block + "\n\n" + full_message) if _steps_block else full_message

        trace_tok = chat_trace.trace_begin()
        tkn = chat_ctx.chat_client_os.set((body.client_os or "").strip()[:32] or None)
        _token_thread = chat_ctx.chat_thread_id.set(body.thread_id)
        snap: dict = {"kb_sources": [], "web_sources": []}
        result = None
        try:
            result = graph.invoke(
                {"messages": [HumanMessage(content=_user_text_with_state)]},
                config={
                    "configurable": {"thread_id": body.thread_id},
                    "recursion_limit": 48,
                },
            )
            snap = chat_trace.snapshot()
        finally:
            chat_trace.trace_reset(trace_tok)
            chat_ctx.chat_client_os.reset(tkn)
            chat_ctx.chat_thread_id.reset(_token_thread)

        msgs = (result or {}).get("messages") or []
        reply = ""
        for m in reversed(msgs):
            if isinstance(m, AIMessage) and not m.tool_calls:
                c = m.content
                if isinstance(c, str):
                    reply = c
                elif isinstance(c, list):
                    parts = []
                    for block in c:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    reply = "\n".join(parts)
                break
        if not reply:
            reply = (
                "(Sin respuesta textual del modelo; revisa el historial o las llamadas a herramientas.)"
            )
        # Red de seguridad: si el LLM pide datos al usuario sin emitir bloque, inyectamos uno genérico.
        reply = ensure_widget_if_info_request(reply)
        # Parseamos el bloque (si existe) antes de strippearlo del texto visible.
        helpdesk_ui = parse_helpdesk_ui_block(reply)
        reply = strip_helpdesk_ui_block(reply)
        desktop_plan = _extract_desktop_plan(msgs)
        desktop_run = _extract_desktop_run(msgs)
        sources, web_search_used = _sources_from_trace(snap)
        tool_calls_used = _extract_tool_trace_last_turn(msgs)
        if not web_search_used:
            web_search_used = any(t.name == "buscar_en_web" for t in tool_calls_used)

        _agent_trace.emit(_turn_id, "phase", {"phase": "composing"})
        _duration_ms = int((_time.time() - _t0) * 1000)
        _agent_trace.emit(_turn_id, "stats", {
            "duration_ms": _duration_ms,
            "tool_calls": len(tool_calls_used or []),
            "kb_hits": len((snap or {}).get("kb_sources") or []),
            "web_hits": len((snap or {}).get("web_sources") or []),
        })
        return ChatOut(
            reply=reply,
            thread_id=body.thread_id,
            vision_used=vision_used,
            desktop_plan=desktop_plan,
            desktop_run=desktop_run,
            helpdesk_ui=helpdesk_ui,
            sources=sources,
            tool_calls_used=tool_calls_used,
            web_search_used=web_search_used,
            turn_id=_turn_id,
        )
    finally:
        _agent_trace.end_turn(_turn_id)


@app.get("/api/tickets")
def list_tickets(thread_id: str | None = None):
    if thread_id:
        return {"tickets": db.listar_tickets_por_thread(thread_id.strip(), 80)}
    return {"tickets": db.listar_tickets(80)}


@app.get("/api/tickets/{ticket_id}")
def one_ticket(ticket_id: str):
    row = db.obtener_ticket(ticket_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return row


@app.delete("/api/tickets/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: str):
    if not db.eliminar_ticket(ticket_id):
        raise HTTPException(status_code=404, detail="Ticket no encontrado")


def _msg_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


@app.get("/api/thread/{thread_id}")
def thread_history(thread_id: str):
    if len(thread_id) < 4 or len(thread_id) > 128:
        raise HTTPException(status_code=400, detail="thread_id inválido")
    try:
        graph = get_graph()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = graph.get_state(cfg)
    messages = (snap.values or {}).get("messages") or []
    out: list[dict] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": _msg_text(m.content)[:6000]})
        elif isinstance(m, AIMessage):
            tc = m.tool_calls or []
            out.append(
                {
                    "role": "assistant",
                    "content": _msg_text(m.content),
                    "tool_calls": [
                        {"name": x.get("name"), "args": x.get("args")}
                        for x in tc
                    ],
                }
            )
        elif isinstance(m, ToolMessage):
            c = _msg_text(m.content)
            if len(c) > 2000:
                c = c[:2000] + "…"
            out.append({"role": "tool", "name": m.name or "", "content": c})
    last_assistant = ""
    for item in reversed(out):
        if item["role"] == "assistant" and (item.get("content") or "").strip():
            last_assistant = item["content"]
            break
    last_assistant = strip_helpdesk_ui_block(last_assistant)
    return {"thread_id": thread_id, "messages": out, "last_assistant_text": last_assistant}


from fastapi.responses import StreamingResponse
from helpdesk_app.vision_loop import events as vl_events


@app.get("/api/desktop/loop/stream/{run_id}")
def loop_stream(run_id: str):
    state = vl_events.get_run(run_id)
    if state is None:
        raise HTTPException(404, "run_id desconocido")

    def gen():
        yield f"event: hello\ndata: {json.dumps({'run_id': run_id})}\n\n"
        while True:
            try:
                msg = state.event_queue.get(timeout=1.0)
            except Exception:
                if state.finished and state.event_queue.empty():
                    yield "event: closed\ndata: {}\n\n"
                    return
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
    return {"active": []}


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


@app.get("/api/agent/trace/{turn_id}")
def agent_trace_stream(turn_id: str):
    run = _agent_trace.get_or_create_run("", turn_id)

    def gen():
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
