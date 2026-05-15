import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from helpdesk_app.config import SQLITE_PATH


def _conn() -> sqlite3.Connection:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SQLITE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                categoria TEXT NOT NULL,
                prioridad TEXT NOT NULL,
                descripcion_usuario TEXT NOT NULL,
                pasos_sugeridos TEXT NOT NULL,
                fuentes_kb TEXT NOT NULL,
                estado TEXT NOT NULL,
                motivo_escalacion TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _migrate_tickets_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_tickets_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tickets)").fetchall()}
    if "resolucion_final" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN resolucion_final TEXT NOT NULL DEFAULT ''")
    if "resolved_at" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN resolved_at TEXT")
    if "thread_id" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN thread_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_thread ON tickets(thread_id)")


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
    thread_clean = thread_id.strip() if isinstance(thread_id, str) and thread_id.strip() else None
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
                thread_clean,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return tid


def actualizar_ticket(
    ticket_id: str,
    *,
    titulo: str | None = None,
    pasos_sugeridos: str | None = None,
    prioridad: str | None = None,
    categoria: str | None = None,
    estado: str | None = None,
    fuentes_kb: list[str] | None = None,
) -> bool:
    """Actualiza campos del ticket; None = no modificar ese campo."""
    cur_row = obtener_ticket(ticket_id)
    if not cur_row:
        return False
    titulo_f = titulo.strip() if titulo is not None else cur_row["titulo"]
    pasos_f = pasos_sugeridos.strip() if pasos_sugeridos is not None else cur_row["pasos_sugeridos"]
    prio_f = prioridad.strip() if prioridad is not None else cur_row["prioridad"]
    cat_f = categoria.strip() if categoria is not None else cur_row["categoria"]
    est_f = estado.strip() if estado is not None else cur_row["estado"]
    if fuentes_kb is not None:
        fuentes_json = json.dumps(fuentes_kb, ensure_ascii=False)
    else:
        fuentes_json = json.dumps(cur_row["fuentes_kb"], ensure_ascii=False)
    conn = _conn()
    try:
        cur = conn.execute(
            """
            UPDATE tickets SET
                titulo = ?, pasos_sugeridos = ?, prioridad = ?, categoria = ?,
                estado = ?, fuentes_kb = ?
            WHERE id = ?
            """,
            (titulo_f, pasos_f, prio_f, cat_f, est_f, fuentes_json, ticket_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def actualizar_estado_ticket(ticket_id: str, estado: str, motivo_escalacion: str | None = None) -> bool:
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE tickets SET estado = ?, motivo_escalacion = COALESCE(?, motivo_escalacion) WHERE id = ?",
            (estado, motivo_escalacion, ticket_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def listar_tickets(limit: int = 50) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM tickets ORDER BY datetime(created_at) DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


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


def obtener_ticket(ticket_id: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def eliminar_ticket(ticket_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def buscar_casos_resueltos(consulta: str, limite: int = 6) -> list[dict[str, Any]]:
    """Tickets en estado resuelto (o cerrado), reordenados por coincidencia léxica simple con la consulta."""
    consulta = (consulta or "").strip().lower()
    tokens = [t for t in re.split(r"\W+", consulta) if len(t) > 2][:14]
    if not tokens and consulta:
        tokens = [consulta]
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM tickets
            WHERE LOWER(estado) IN ('resuelto', 'cerrado')
            ORDER BY datetime(created_at) DESC
            LIMIT 250
            """
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in rows:
        d = _row_to_dict(r)
        blob = " ".join(
            [
                str(d.get("titulo", "")),
                str(d.get("descripcion_usuario", "")),
                str(d.get("pasos_sugeridos", "")),
                str(d.get("resolucion_final", "")),
                str(d.get("categoria", "")),
            ]
        ).lower()
        score = sum(1 for t in tokens if t in blob) if tokens else 0
        scored.append((score, d))
    scored.sort(key=lambda x: (x[0], x[1].get("created_at") or ""), reverse=True)
    best_score = scored[0][0] if scored else 0
    if tokens and best_score == 0:
        return [_row_to_dict(r) for r in rows[:limite]]
    return [d for _, d in scored[:limite]]


def registrar_ticket_resuelto(ticket_id: str, leccion_resumida: str) -> bool:
    """Marca el ticket como resuelto y guarda la lección (texto breve, sin PII)."""
    leccion = (leccion_resumida or "").strip()
    if len(leccion) < 24:
        return False
    tid = ticket_id.strip()
    if len(tid) < 8:
        return False
    now = datetime.now(timezone.utc).isoformat()
    conn = _conn()
    try:
        cur = conn.execute(
            """
            UPDATE tickets SET
                estado = 'resuelto',
                resolucion_final = ?,
                resolved_at = ?
            WHERE id = ?
            """,
            (leccion, now, tid),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["fuentes_kb"] = json.loads(d["fuentes_kb"])
    except (json.JSONDecodeError, TypeError):
        d["fuentes_kb"] = []
    return d
