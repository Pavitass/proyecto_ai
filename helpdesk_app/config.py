from pathlib import Path

from dotenv import load_dotenv
import os

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT.parent / ".env", override=False)

BASE_DIR = _ROOT
DATA_KB_DIR = BASE_DIR / "data" / "kb"
_chroma_override = (os.getenv("HELPDESK_CHROMA_DIR") or "").strip()
CHROMA_DIR = (
    Path(_chroma_override).expanduser().resolve()
    if _chroma_override
    else (BASE_DIR / ".chroma").resolve()
)
SQLITE_PATH = BASE_DIR / "data" / "tickets.sqlite3"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")

# Visión: por defecto Google (Gemini). openai = API compatible OpenAI solo si lo defines explícito.
HELPDESK_VISION_BACKEND = os.getenv("HELPDESK_VISION_BACKEND", "google").lower()
HELPDESK_VISION_OPENAI_API_KEY = os.getenv(
    "HELPDESK_VISION_OPENAI_API_KEY", ""
).strip() or OPENAI_API_KEY
HELPDESK_VISION_OPENAI_BASE_URL = os.getenv(
    "HELPDESK_VISION_OPENAI_BASE_URL", "https://api.openai.com/v1"
).rstrip("/")
HELPDESK_VISION_OPENAI_MODEL = os.getenv("HELPDESK_VISION_OPENAI_MODEL", "gpt-4o-mini")

# google | hf (local, sentence-transformers) | auto (solo si quieres: con GOOGLE_API_KEY → google)
# Por defecto **hf**: el RAG no depende de la API de embeddings de Google (el chat/visión pueden seguir usando GOOGLE_API_KEY).
HELPDESK_EMBEDDINGS = os.getenv("HELPDESK_EMBEDDINGS", "hf").lower()
HF_EMBEDDING_MODEL = os.getenv(
    "HELPDESK_HF_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
# Solo si HELPDESK_EMBEDDINGS=google (o auto con clave). Modelo actual recomendado por la API Gemini.
EMBEDDING_MODEL = os.getenv("HELPDESK_EMBEDDING_MODEL", "gemini-embedding-001")

HELPDESK_LLM = os.getenv("HELPDESK_LLM", "auto").lower()


def use_deepseek_llm() -> bool:
    """auto: usa DeepSeek si existe DEEPSEEK_API_KEY; si no, Gemini."""
    if HELPDESK_LLM == "deepseek":
        return True
    if HELPDESK_LLM == "google":
        return False
    return bool(DEEPSEEK_API_KEY)


_default_chat = "deepseek-chat" if use_deepseek_llm() else "gemini-2.0-flash"
CHAT_MODEL = os.getenv("HELPDESK_CHAT_MODEL", _default_chat)

LLM_TEMPERATURE = float(os.getenv("HELPDESK_TEMPERATURE", "0.15"))

# Modelo solo para describir capturas con Gemini (backend google).
VISION_MODEL = os.getenv("HELPDESK_VISION_MODEL", "gemini-2.0-flash")


def resolve_vision_backend() -> str:
    """google | openai | none (sin claves para ninguno)."""
    b = HELPDESK_VISION_BACKEND
    if b in ("openai", "openai_compatible"):
        return "openai" if HELPDESK_VISION_OPENAI_API_KEY else "none"
    if b in ("google", "gemini"):
        return "google" if GOOGLE_API_KEY else "none"
    # auto: Gemini si hay clave; si no, OpenAI-compatible (solo si no quieres forzar google por defecto)
    if GOOGLE_API_KEY:
        return "google"
    if HELPDESK_VISION_OPENAI_API_KEY:
        return "openai"
    return "none"


def vision_is_configured() -> bool:
    return resolve_vision_backend() in ("google", "openai")


def desktop_py_exec_enabled() -> bool:
    """Si true, /api/desktop/exec puede usar PyAutoGUI (solo peticiones a localhost)."""
    return os.getenv("HELPDESK_DESKTOP_PY_EXEC", "").strip().lower() in ("1", "true", "yes", "on")


def desktop_force_human_ack() -> bool:
    """Si true, toda acción ejecutada vía API requiere human_ack=true (modo paranoico)."""
    return os.getenv("HELPDESK_DESKTOP_FORCE_ACK", "").strip().lower() in ("1", "true", "yes", "on")


def vision_capabilities_payload() -> dict:
    """Para /api/capabilities y depuración."""
    backend = resolve_vision_backend()
    if backend == "google":
        return {
            "vision": True,
            "vision_backend": "google",
            "vision_model": VISION_MODEL,
            "desktop_py_exec": desktop_py_exec_enabled(),
            "desktop_force_human_ack": desktop_force_human_ack(),
        }
    if backend == "openai":
        return {
            "vision": True,
            "vision_backend": "openai_compatible",
            "vision_model": HELPDESK_VISION_OPENAI_MODEL,
            "vision_base_url": HELPDESK_VISION_OPENAI_BASE_URL,
            "desktop_py_exec": desktop_py_exec_enabled(),
            "desktop_force_human_ack": desktop_force_human_ack(),
        }
    return {
        "vision": False,
        "vision_backend": None,
        "vision_model": None,
        "desktop_py_exec": desktop_py_exec_enabled(),
        "desktop_force_human_ack": desktop_force_human_ack(),
    }


def embedding_backend() -> str:
    """hf | google explícitos. auto: si hay GOOGLE_API_KEY → google; si no → hf."""
    if HELPDESK_EMBEDDINGS in ("google", "hf"):
        return HELPDESK_EMBEDDINGS
    if HELPDESK_EMBEDDINGS == "auto" and GOOGLE_API_KEY:
        return "google"
    return "hf"
