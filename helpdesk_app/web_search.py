"""Búsqueda web ligera (DuckDuckGo) para complementar la KB.

Evita ruido típico (diccionarios que matchean “turn”, “battery” suelto, etc.) y prioriza
documentación Apple / Microsoft cuando la consulta parece de sistema operativo.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Hosts o patrones que casi nunca aportan soporte TI y suelen colarse con palabras inglesas cortas.
_NOISE_HOST_SUBSTR = (
    "cambridge.org",
    "dictionary.",
    "wordreference",
    "linguee.com",
    "reverso.net",
    "ingles.com",
    "spanishdict.com",
    "collinsdictionary",
    "thefreedictionary",
    "diccionario.",
    "merriam-webster",
    "wiktionary.org",
    "translate.google",
    "deepl.com",
    "context.reverso",
)

_APPLE_QUERY_HINTS = (
    "macos",
    "mac os",
    "sequoia",
    "ventura",
    "sonoma",
    "monterey",
    "big sur",
    "catalina",
    "apple silicon",
    "iphone",
    "ipad",
    "macbook",
    "imac",
    "low power",
    "batería",
    "battery",
    "icloud",
    "airdrop",
    "finder",
    "spotlight",
    "mac ",
)

_MS_QUERY_HINTS = (
    "windows 11",
    "windows 10",
    "win32",
    "microsoft 365",
    "outlook",
    "edge ",
    "defender",
)


def _looks_apple_context(q: str) -> bool:
    ql = q.lower()
    return any(h in ql for h in _APPLE_QUERY_HINTS)


def _looks_microsoft_context(q: str) -> bool:
    ql = q.lower()
    return any(h in ql for h in _MS_QUERY_HINTS)


def _is_noise_hit(h: dict[str, Any]) -> bool:
    u = (h.get("href") or "").lower()
    t = (h.get("title") or "").lower()
    if not u.startswith("http"):
        return True
    try:
        host = urlparse(u).hostname or ""
    except ValueError:
        return True
    host = host.lower()
    for n in _NOISE_HOST_SUBSTR:
        if n in host or n in u:
            return True
    # Título típico de traductor sin contexto Apple/Microsoft
    if any(x in t for x in ("traductor", "translator", "dictionary", "diccionario")):
        if "apple" not in t and "mac" not in t and "microsoft" not in t and "windows" not in t:
            return True
    return False


def _result_score(h: dict[str, Any]) -> int:
    u = (h.get("href") or "").lower()
    if "support.apple.com" in u:
        return 5
    if "discussions.apple.com" in u:
        return 4
    if "apple.com" in u:
        return 3
    if "learn.microsoft.com" in u or "support.microsoft.com" in u:
        return 3
    if "microsoft.com" in u:
        return 2
    return 0


def _queries_for_ddgs(q: str) -> list[str]:
    """Varias formulaciones: primero documentación oficial si aplica."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    ql = q.lower()
    out: list[str] = []
    if "site:" not in ql and _looks_apple_context(q):
        # Búsqueda acotada a soporte Apple (evita diccionarios por “turn”, “mode”, etc.)
        out.append(f"site:support.apple.com {q}")
        out.append(f"site:support.apple.com Mac battery Low Power Mode {q}")
    if "site:" not in ql and _looks_microsoft_context(q):
        out.append(f"site:learn.microsoft.com {q}")
        out.append(f"site:support.microsoft.com {q}")
    out.append(q)
    # Desduplicar manteniendo orden
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq[:4]


def _collect_hits(queries: list[str], want: int) -> list[dict[str, Any]]:
    from duckduckgo_search import DDGS

    merged: list[dict[str, Any]] = []
    seen_href: set[str] = set()
    per_query = max(6, min(want + 4, 12))

    with DDGS() as ddgs:
        for query in queries:
            try:
                it = ddgs.text(query, max_results=per_query)
            except Exception:
                continue
            for r in it:
                if not isinstance(r, dict):
                    continue
                h = {
                    "title": str(r.get("title") or "").strip(),
                    "href": str(r.get("href") or r.get("url") or "").strip(),
                    "body": str(r.get("body") or "").strip(),
                }
                href = h["href"]
                if not href or href in seen_href:
                    continue
                if _is_noise_hit(h):
                    continue
                seen_href.add(href)
                merged.append(h)
                if len(merged) >= want * 3:
                    break
            if len(merged) >= want * 2:
                break

    merged.sort(key=_result_score, reverse=True)
    return merged[:want]


def _english_turn_noise_cleanup(q: str) -> str:
    """Evita consultas del estilo 'how to turn off X' donde DDG se obsesiona con 'turn'."""
    s = q.strip()
    low = s.lower()
    # Sustituye patrón muy común por formulación más técnica
    s = re.sub(
        r"(?i)^how\s+to\s+turn\s+off\s+",
        "disable ",
        s,
    )
    s = re.sub(
        r"(?i)^how\s+to\s+turn\s+on\s+",
        "enable ",
        s,
    )
    s = re.sub(r"(?i)\bturn\s+off\b", "disable", s)
    s = re.sub(r"(?i)\bturn\s+on\b", "enable", s)
    if s != q.strip() and _looks_apple_context(low):
        s = f"{s} macOS Apple"
    return s.strip()


def buscar_web_ddgs(consulta: str, max_results: int = 5) -> tuple[str, list[dict[str, Any]]]:
    """
    Devuelve (texto_para_llm, lista de dicts title/href/body).
    Si falla la red o la librería, texto explica el error y lista vacía.
    """
    q = (consulta or "").strip()
    if len(q) < 2:
        return ("Consulta demasiado corta para buscar en la web.", [])
    max_results = max(1, min(int(max_results), 8))
    try:
        from duckduckgo_search import DDGS  # noqa: F401
    except ImportError:
        return (
            "El paquete duckduckgo-search no está instalado; no se puede buscar en la web en este entorno.",
            [],
        )

    q_refined = _english_turn_noise_cleanup(q)
    queries = _queries_for_ddgs(q_refined)
    if not queries:
        queries = [q]

    hits: list[dict[str, Any]] = []
    try:
        hits = _collect_hits(queries, max_results)
    except Exception as e:
        return (f"Búsqueda web no disponible en este momento ({e}).", [])

    # Si todo era ruido, un último intento muy genérico hacia Apple
    if not hits and _looks_apple_context(q):
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                fallback = "site:support.apple.com Mac Low Power Mode battery"
                for r in ddgs.text(fallback, max_results=max_results):
                    if not isinstance(r, dict):
                        continue
                    h = {
                        "title": str(r.get("title") or "").strip(),
                        "href": str(r.get("href") or r.get("url") or "").strip(),
                        "body": str(r.get("body") or "").strip(),
                    }
                    if _is_noise_hit(h):
                        continue
                    hits.append(h)
                    if len(hits) >= max_results:
                        break
        except Exception:
            pass

    if not hits:
        return (
            "No se obtuvieron resultados web útiles (o solo había páginas de diccionario/traducción irrelevantes). "
            "Reformula la consulta con términos más específicos (p. ej. «Apple soporte modo bajo consumo Mac») "
            "o usa la KB interna.",
            [],
        )

    lines: list[str] = [
        f"Resultados web filtrados (DuckDuckGo). Consultas usadas: {', '.join(queries[:3])}\n"
    ]
    for i, h in enumerate(hits, 1):
        body = h["body"][:400] + ("…" if len(h["body"]) > 400 else "")
        lines.append(f"{i}. **{h['title']}**\n   URL: {h['href']}\n   {body}\n")
    return ("\n".join(lines), hits)
