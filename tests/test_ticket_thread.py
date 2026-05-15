import os
import tempfile

import pytest


@pytest.fixture
def fresh_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
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
    c = fresh_db.crear_ticket(titulo="c", categoria="c", prioridad="alta", descripcion_usuario="d", pasos_sugeridos="p", fuentes_kb=[], estado="abierto")
    only1 = fresh_db.listar_tickets_por_thread("thr-1")
    ids = {t["id"] for t in only1}
    assert a in ids and b not in ids and c not in ids


def test_listar_tickets_includes_thread_id_field(fresh_db):
    fresh_db.crear_ticket(titulo="a", categoria="c", prioridad="alta", descripcion_usuario="d", pasos_sugeridos="p", fuentes_kb=[], estado="abierto", thread_id="thr-1")
    all_t = fresh_db.listar_tickets(10)
    assert all_t and "thread_id" in all_t[0]
