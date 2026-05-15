import json
from datetime import datetime, timezone

from langchain_core.tools import tool

from helpdesk_app import agent_trace as _trace
from helpdesk_app import chat_trace
from helpdesk_app import db
from helpdesk_app import chat_context as chat_ctx
from helpdesk_app.config import DATA_KB_DIR
from helpdesk_app.desktop_plan import DesktopPlanError, generate_desktop_plan
from helpdesk_app.rag import buscar_contexto
from helpdesk_app.web_search import buscar_web_ddgs


def _emit(type_: str, payload: dict) -> None:
    tid = (chat_ctx.chat_thread_id.get() or "").strip()
    if not tid:
        return
    _trace.emit_by_thread(tid, type_, payload)


@tool
def buscar_casos_resueltos_previos(consulta: str) -> str:
    """Busca en tickets ya **resueltos** (base interna) casos parecidos a la consulta.
    Úsalo después de buscar_en_base_de_conocimiento cuando haya una incidencia concreta,
    para reutilizar lecciones reales de cierres anteriores (síntomas, categoría, resolución guardada)."""
    _emit("tool_start", {"name": "buscar_casos_resueltos_previos", "args_preview": str(consulta)[:80]})
    try:
        casos = db.buscar_casos_resueltos(consulta, limite=6)
        if not casos:
            _emit("tool_end", {"name": "buscar_casos_resueltos_previos", "ok": True, "summary": "0 casos"})
            return (
                "No hay tickets resueltos indexados aún, o ninguno coincide de forma útil. "
                "Sigue con la KB y el ticket actual; cuando el caso cierre, registra lección con registrar_ticket_resuelto."
            )
        bloques: list[str] = []
        for i, c in enumerate(casos, 1):
            rid = c.get("id", "")
            lec = (c.get("resolucion_final") or "").strip()
            lec_txt = f"\n**Lección registrada:** {lec}" if lec else ""
            bloques.append(
                f"--- Caso resuelto {i} (id `{rid}`) — {c.get('categoria', '')} — {c.get('prioridad', '')} ---\n"
                f"**Título:** {c.get('titulo', '')}\n"
                f"**Descripción original:** {c.get('descripcion_usuario', '')[:900]}"
                f"{'…' if len(str(c.get('descripcion_usuario', ''))) > 900 else ''}"
                f"{lec_txt}"
            )
        _emit("tool_end", {"name": "buscar_casos_resueltos_previos", "ok": True, "summary": f"{len(casos)} casos"})
        return "\n\n".join(bloques)
    except Exception as e:
        _emit("tool_end", {"name": "buscar_casos_resueltos_previos", "ok": False, "summary": str(e)[:120]})
        raise


@tool
def registrar_ticket_resuelto(ticket_id: str, leccion_resumida: str) -> str:
    """Cuando el usuario confirma que el problema quedó resuelto o el caso está cerrado con éxito.
    Guarda una **lección breve** (qué fallaba, qué se hizo, qué verificar la próxima vez), **sin** correos,
    nombres de personas, teléfonos ni contraseñas. Mínimo unas pocas frases. Los futuros casos podrán
    reutilizar esta lección vía buscar_casos_resueltos_previos."""
    _emit("tool_start", {"name": "registrar_ticket_resuelto", "args_preview": str(ticket_id)[:80]})
    try:
        ok = db.registrar_ticket_resuelto(ticket_id.strip(), leccion_resumida.strip())
        if not ok:
            _emit("tool_end", {"name": "registrar_ticket_resuelto", "ok": True, "summary": "no registrado"})
            return (
                "No se pudo registrar: comprueba el **ticket_id** completo y que la lección tenga "
                "suficiente texto (varias frases, contenido real). Si el ticket no existe, créalo antes."
            )
        _emit("ticket_op", {"op": "resolver", "ticket_id": ticket_id.strip(), "titulo": ""})
        _emit("tool_end", {"name": "registrar_ticket_resuelto", "ok": True, "summary": f"ticket {ticket_id.strip()[:8]} resuelto"})
        return (
            f"Ticket {ticket_id.strip()} marcado como **resuelto** y lección guardada. "
            "Los casos futuros similares podrán encontrar este cierre con buscar_casos_resueltos_previos."
        )
    except Exception as e:
        _emit("tool_end", {"name": "registrar_ticket_resuelto", "ok": False, "summary": str(e)[:120]})
        raise


@tool
def buscar_en_base_de_conocimiento(consulta: str, top_k: int = 4, diversidad: bool = False) -> str:
    """Busca en la KB (RAG). Úsalo en cuanto haya un caso concreto. Parámetros:
    - top_k: número de fragmentos (1-8 razonable, por defecto 4).
    - diversidad: si True usa MMR (resultados más diversos)."""
    _emit("tool_start", {"name": "buscar_en_base_de_conocimiento", "args_preview": str(consulta)[:80]})
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


@tool
def buscar_en_web(consulta: str) -> str:
    """Busca en Internet (DuckDuckGo) cuando la KB interna no cubre el caso, hace falta información reciente
    o el usuario pide explícitamente fuentes externas. Resume resultados citando **título y URL** en tu respuesta.
    Formula la **consulta** de forma concreta: preferible **español** + producto/contexto (p. ej. «modo bajo consumo Mac Apple»).
    Evita consultas muy cortas en inglés del tipo solo «how to turn off …» (suelen devolver diccionarios por la palabra *turn*).
    Si la información es útil para futuros tickets, pregunta al usuario si desea **guardar un resumen en la KB**;
    solo si confirma, usa guardar_snippet_en_kb."""
    _emit("tool_start", {"name": "buscar_en_web", "args_preview": str(consulta)[:80]})
    try:
        texto, hits = buscar_web_ddgs(consulta, max_results=5)
        for h in hits:
            title = h.get("title") or ""
            url = h.get("href") or ""
            snippet = h.get("body") or ""
            chat_trace.add_web_source(title, url, snippet)
            _emit("web_hit", {"title": title, "url": url, "snippet": snippet[:120]})
        _emit("tool_end", {"name": "buscar_en_web", "ok": True, "summary": f"{len(hits)} resultados"})
        return texto
    except Exception as e:
        _emit("tool_end", {"name": "buscar_en_web", "ok": False, "summary": str(e)[:120]})
        raise


_KB_IMPORT_FILE = "99_importaciones_usuario.md"


@tool
def guardar_snippet_en_kb(
    titulo: str,
    resumen_markdown: str,
    fuente_url: str = "",
) -> str:
    """Solo tras **confirmación explícita del usuario** de añadir contenido a la KB interna (p. ej. “sí,
    guárdalo”, “añádelo a la base de conocimiento”). Escribe un bloque en `data/kb/99_importaciones_usuario.md`.
    Sin datos personales, contraseñas ni secretos. Texto conciso (guía TI)."""
    _emit("tool_start", {"name": "guardar_snippet_en_kb", "args_preview": str(titulo)[:80]})
    try:
        title = (titulo or "").strip()
        body = (resumen_markdown or "").strip()
        if len(title) < 4 or len(body) < 40:
            msg = "Título o resumen demasiado cortos; pide al usuario un poco más de detalle antes de guardar."
            _emit("tool_end", {"name": "guardar_snippet_en_kb", "ok": True, "summary": msg[:120]})
            return msg
        if len(body) > 12000:
            msg = "Resumen demasiado largo; acorta a lo esencial (máx. ~12000 caracteres)."
            _emit("tool_end", {"name": "guardar_snippet_en_kb", "ok": True, "summary": msg[:120]})
            return msg
        url = (fuente_url or "").strip()[:500]
        path = DATA_KB_DIR / _KB_IMPORT_FILE
        DATA_KB_DIR.mkdir(parents=True, exist_ok=True)
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        block = (
            f"\n\n## {title}\n\n"
            f"_Importado: {when}_"
            + (f" · _Fuente:_ {url}\n\n" if url else "\n\n")
            + body
            + "\n"
        )
        try:
            prev = path.read_text(encoding="utf-8") if path.exists() else ""
            if not prev.strip():
                path.write_text(
                    "# Importaciones a la KB (usuario / asistente)\n\n"
                    "> Revisar antes de producción; convierte a ficheros temáticos si crece.\n"
                    + block,
                    encoding="utf-8",
                )
            else:
                path.write_text(prev.rstrip() + block, encoding="utf-8")
        except OSError as e:
            msg = f"No se pudo escribir en la KB: {e}"
            _emit("tool_end", {"name": "guardar_snippet_en_kb", "ok": True, "summary": msg[:120]})
            return msg
        _emit("tool_end", {"name": "guardar_snippet_en_kb", "ok": True, "summary": "snippet añadido"})
        return (
            f"Fragmento añadido a `{_KB_IMPORT_FILE}`. "
            "Recuerda al usuario que debe **reindexar** el RAG (borrar la carpeta `.chroma` del proyecto o "
            "`HELPDESK_CHROMA_DIR`) y reiniciar el servidor para que los embeddings incluyan el nuevo texto."
        )
    except Exception as e:
        _emit("tool_end", {"name": "guardar_snippet_en_kb", "ok": False, "summary": str(e)[:120]})
        raise


@tool
def crear_ticket_de_servicio(
    titulo: str,
    categoria: str,
    prioridad: str,
    descripcion_usuario: str,
    pasos_sugeridos: str,
    fuentes_documentos: str,
    estado_ticket: str = "en_diagnostico",
) -> str:
    """Registra un ticket en cuanto haya un caso concreto (comportamiento proactivo).
    estado_ticket: en_diagnostico (apertura inmediata), pendiente_validacion, abierto, etc.
    fuentes_documentos: nombres de archivos KB separados por coma, o 'ninguna'."""
    _emit("tool_start", {"name": "crear_ticket_de_servicio", "args_preview": str(titulo)[:80]})
    try:
        fuentes = [x.strip() for x in fuentes_documentos.split(",") if x.strip()]
        est = (estado_ticket or "en_diagnostico").strip() or "en_diagnostico"
        _tid_ctx = (chat_ctx.chat_thread_id.get() or "").strip() or None
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
        _emit("ticket_op", {"op": "crear", "ticket_id": tid, "titulo": titulo})
        _emit("tool_end", {"name": "crear_ticket_de_servicio", "ok": True, "summary": f"ticket {str(tid)[:8]}"})
        return (
            f"Ticket creado. ID: {tid}. "
            "Comunícalo al usuario al inicio de tu respuesta; si afinas el plan, usa actualizar_ticket_de_servicio."
        )
    except Exception as e:
        _emit("tool_end", {"name": "crear_ticket_de_servicio", "ok": False, "summary": str(e)[:120]})
        raise


@tool
def actualizar_ticket_de_servicio(
    ticket_id: str,
    pasos_sugeridos: str = "",
    titulo: str = "",
    prioridad: str = "",
    categoria: str = "",
    fuentes_documentos: str = "",
    estado_ticket: str = "",
) -> str:
    """Actualiza un ticket ya existente tras más KB o diagnóstico. Deja en blanco los campos que no cambien."""
    _emit("tool_start", {"name": "actualizar_ticket_de_servicio", "args_preview": str(ticket_id)[:80]})
    try:
        kw: dict = {}
        if pasos_sugeridos.strip():
            kw["pasos_sugeridos"] = pasos_sugeridos.strip()
        if titulo.strip():
            kw["titulo"] = titulo.strip()
        if prioridad.strip():
            kw["prioridad"] = prioridad.strip()
        if categoria.strip():
            kw["categoria"] = categoria.strip()
        if estado_ticket.strip():
            kw["estado"] = estado_ticket.strip()
        if fuentes_documentos.strip():
            kw["fuentes_kb"] = [x.strip() for x in fuentes_documentos.split(",") if x.strip()]
        if not kw:
            _emit("tool_end", {"name": "actualizar_ticket_de_servicio", "ok": True, "summary": "sin cambios"})
            return (
                "No se indicó ningún cambio. Indica al menos uno: pasos_sugeridos, titulo, prioridad, "
                "categoria, estado_ticket o fuentes_documentos."
            )
        ok = db.actualizar_ticket(ticket_id.strip(), **kw)
        if not ok:
            _emit("tool_end", {"name": "actualizar_ticket_de_servicio", "ok": True, "summary": "no encontrado"})
            return "Ticket no encontrado; verifica el ID."
        _emit("ticket_op", {"op": "actualizar", "ticket_id": ticket_id.strip(), "titulo": ""})
        _emit("tool_end", {"name": "actualizar_ticket_de_servicio", "ok": True, "summary": f"ticket {ticket_id.strip()[:8]} actualizado"})
        return f"Ticket {ticket_id} actualizado."
    except Exception as e:
        _emit("tool_end", {"name": "actualizar_ticket_de_servicio", "ok": False, "summary": str(e)[:120]})
        raise


@tool
def escalar_a_especialista(ticket_id: str, motivo: str) -> str:
    """Marca un ticket para intervención humana cuando falten permisos, datos sensibles o la KB no cubre el caso."""
    _emit("tool_start", {"name": "escalar_a_especialista", "args_preview": str(ticket_id)[:80]})
    try:
        ok = db.actualizar_estado_ticket(
            ticket_id.strip(),
            "escalado",
            motivo_escalacion=motivo.strip(),
        )
        if not ok:
            _emit("tool_end", {"name": "escalar_a_especialista", "ok": True, "summary": "no encontrado"})
            return (
                "No se encontró el ticket indicado. Crea antes un ticket con crear_ticket_de_servicio "
                "o verifica el ID."
            )
        _emit("ticket_op", {"op": "escalar", "ticket_id": ticket_id.strip(), "titulo": ""})
        _emit("tool_end", {"name": "escalar_a_especialista", "ok": True, "summary": f"ticket {ticket_id.strip()[:8]} escalado"})
        return f"Ticket {ticket_id} marcado como escalado. Motivo registrado para el equipo humano."
    except Exception as e:
        _emit("tool_end", {"name": "escalar_a_especialista", "ok": False, "summary": str(e)[:120]})
        raise


@tool
def preparar_plan_escritorio(goal: str) -> str:
    """Genera un plan JSON para **automatizar el escritorio** (mover ratón, clic, teclado, atajos tipo Spotlight).
    Úsalo cuando el usuario pida hacer algo **en su propio equipo** (abrir ajustes, desactivar ahorro de batería
    si es posible sin contraseña de admin, buscar en el sistema, etc.). No lo uses para preguntas solo
    informativas, ni para borrar datos o operaciones irreversibles sin que el usuario lo pida con claridad.
    El parámetro goal debe ser una frase corta y concreta en español.
    Tras llamarla, resume al usuario el plan en lenguaje natural; la interfaz puede mostrar botones de ejecución."""
    _emit("tool_start", {"name": "preparar_plan_escritorio", "args_preview": str(goal)[:80]})
    try:
        g = (goal or "").strip()
        if len(g) < 4:
            msg = "Objetivo demasiado corto."
            _emit("tool_end", {"name": "preparar_plan_escritorio", "ok": True, "summary": msg[:120]})
            return json.dumps(
                {"error": msg, "rationale": "", "actions": []},
                ensure_ascii=False,
            )
        co = (chat_ctx.chat_client_os.get() or "").strip() or None
        try:
            plan = generate_desktop_plan(g, None, client_os=co)
            actions = plan.get("actions", []) if isinstance(plan, dict) else []
            _emit("tool_end", {"name": "preparar_plan_escritorio", "ok": True, "summary": f"{len(actions)} acciones"})
            return json.dumps(plan, ensure_ascii=False)
        except DesktopPlanError as e:
            _emit("tool_end", {"name": "preparar_plan_escritorio", "ok": True, "summary": str(e)[:120]})
            return json.dumps({"error": str(e), "rationale": "", "actions": []}, ensure_ascii=False)
    except Exception as e:
        _emit("tool_end", {"name": "preparar_plan_escritorio", "ok": False, "summary": str(e)[:120]})
        raise


@tool
def ejecutar_tarea_escritorio(goal: str) -> str:
    """Ejecuta un objetivo paso a paso en el escritorio mirando capturas de pantalla.
    Loop: captura → razona → UNA acción → verifica → repite (máx 20 pasos, 90s totales).
    Pide aprobación humana en cada paso marcado sensible. Úsalo SOLO si el usuario
    pidió explícitamente que el sistema haga algo en su equipo (p. ej. "envíalo en mi Outlook",
    "abre Ajustes y cambia X"). Devuelve resumen del resultado, no inventes pasos."""
    _emit("tool_start", {"name": "ejecutar_tarea_escritorio", "args_preview": str(goal)[:80]})
    try:
        from helpdesk_app.vision_loop import events as ev
        from helpdesk_app.vision_loop.loop import run_loop

        g = (goal or "").strip()
        if len(g) < 4:
            _emit("tool_end", {"name": "ejecutar_tarea_escritorio", "ok": True, "summary": "fail"})
            return json.dumps({"status": "fail", "reason": "Objetivo demasiado corto."}, ensure_ascii=False)

        state = ev.create_run(g)
        chat_trace.add_kb_source("[automation]", f"run_id={state.run_id} goal={g[:120]}")
        outcome = run_loop(state)
        _emit("tool_end", {"name": "ejecutar_tarea_escritorio", "ok": True, "summary": str(outcome.status)[:120]})
        return json.dumps({
            "run_id": state.run_id,
            "status": outcome.status,
            "reason": outcome.reason,
            "steps": outcome.steps,
        }, ensure_ascii=False)
    except Exception as e:
        _emit("tool_end", {"name": "ejecutar_tarea_escritorio", "ok": False, "summary": str(e)[:120]})
        raise


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
