import pytest
from helpdesk_app import rag

def test_buscar_contexto_accepts_top_k_and_mmr():
    try:
        rag.buscar_contexto("vpn no conecta", k=2, mmr=False)
        rag.buscar_contexto("vpn no conecta", k=2, mmr=True)
    except TypeError as e:
        pytest.fail(f"buscar_contexto rejected new kwargs: {e}")


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
