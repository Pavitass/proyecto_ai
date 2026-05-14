import pytest
from helpdesk_app import rag

def test_buscar_contexto_accepts_top_k_and_mmr():
    try:
        rag.buscar_contexto("vpn no conecta", k=2, mmr=False)
        rag.buscar_contexto("vpn no conecta", k=2, mmr=True)
    except TypeError as e:
        pytest.fail(f"buscar_contexto rejected new kwargs: {e}")
