import shutil
import stat
import sys
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from helpdesk_app.config import (
    CHROMA_DIR,
    DATA_KB_DIR,
    EMBEDDING_MODEL,
    GOOGLE_API_KEY,
    HF_EMBEDDING_MODEL,
    embedding_backend,
)

_vectorstore: Chroma | None = None

from threading import Lock

_QUERY_CACHE: dict[tuple[str, int, bool], list[Document]] = {}
_QUERY_CACHE_LOCK = Lock()
_QUERY_CACHE_MAX = 64


def invalidate_cache() -> None:
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE.clear()


def _collection_name() -> str:
    return f"helpdesk_kb_{embedding_backend()}"


def _ensure_chroma_dir_writable() -> None:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    probe = CHROMA_DIR / ".helpdesk_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"No se puede escribir en la carpeta de Chroma ({CHROMA_DIR}). "
            "Revisa permisos (p. ej. chmod -R u+w) o define la variable de entorno "
            "HELPDESK_CHROMA_DIR apuntando a un directorio donde tu usuario tenga escritura."
        ) from e


def _relax_chroma_sqlite_files(chroma_dir: Path) -> None:
    """SQLite 1032 (readonly) a veces se debe a permisos 444 en chroma.sqlite3."""
    if sys.platform == "win32":
        return
    mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
    for name in ("chroma.sqlite3", "chroma.sqlite3-wal", "chroma.sqlite3-shm"):
        p = chroma_dir / name
        if p.exists():
            try:
                p.chmod(mode)
            except OSError:
                pass


def _is_chroma_readonly_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "readonly" in s or "1032" in s or "read-only" in s


def _make_embeddings():
    be = embedding_backend()
    if be == "google":
        if not GOOGLE_API_KEY:
            raise RuntimeError(
                "Embeddings Google requieren GOOGLE_API_KEY, o bien define HELPDESK_EMBEDDINGS=hf "
                "y usa embeddings locales (sentence-transformers)."
            )
        return GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=GOOGLE_API_KEY,
        )
    from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=HF_EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _load_file_documents() -> list[Document]:
    docs: list[Document] = []
    if not DATA_KB_DIR.exists():
        return docs
    for path in sorted(DATA_KB_DIR.glob("*.md")):
        docs.extend(TextLoader(str(path), encoding="utf-8").load())
    for path in sorted(DATA_KB_DIR.glob("*.pdf")):
        docs.extend(PyPDFLoader(str(path)).load())
    return docs


def _build_vectorstore() -> Chroma:
    embeddings = _make_embeddings()
    raw_docs = _load_file_documents()
    if not raw_docs:
        raise RuntimeError(
            f"No hay documentos en {DATA_KB_DIR}. Añade archivos .md o .pdf a data/kb/."
        )
    splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=180)
    splits = splitter.split_documents(raw_docs)
    _ensure_chroma_dir_writable()
    _relax_chroma_sqlite_files(CHROMA_DIR)

    def _from_docs() -> Chroma:
        return Chroma.from_documents(
            documents=splits,
            embedding=embeddings,
            persist_directory=str(CHROMA_DIR),
            collection_name=_collection_name(),
        )

    try:
        return _from_docs()
    except Exception as e:
        if not _is_chroma_readonly_error(e):
            raise
        shutil.rmtree(CHROMA_DIR, ignore_errors=True)
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _ensure_chroma_dir_writable()
        try:
            return _from_docs()
        except Exception as e2:
            raise RuntimeError(
                "Chroma no pudo escribir la base de datos (solo lectura). "
                f"Borra manualmente la carpeta {CHROMA_DIR} o define HELPDESK_CHROMA_DIR. Detalle: {e2}"
            ) from e2


def get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore
    embeddings = _make_embeddings()
    marker = CHROMA_DIR / "chroma.sqlite3"
    collection = _collection_name()
    if marker.exists():
        _relax_chroma_sqlite_files(CHROMA_DIR)
        _ensure_chroma_dir_writable()
        _vectorstore = Chroma(
            collection_name=collection,
            embedding_function=embeddings,
            persist_directory=str(CHROMA_DIR),
        )
        try:
            n = _vectorstore._collection.count()
        except Exception:
            n = 0
        if n == 0:
            _vectorstore = None
            shutil.rmtree(CHROMA_DIR, ignore_errors=True)
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            _vectorstore = _build_vectorstore()
    else:
        _vectorstore = _build_vectorstore()
    return _vectorstore


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
            _QUERY_CACHE.pop(next(iter(_QUERY_CACHE)))
        _QUERY_CACHE[key] = result
    return result


def warmup() -> None:
    """Pre-build the vectorstore so the first user query doesn't pay the cold-start cost."""
    try:
        get_vectorstore()
    except Exception as e:
        import logging
        logging.getLogger("helpdesk.rag").warning("RAG warmup skipped: %s", e)
