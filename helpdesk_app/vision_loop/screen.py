"""Captura de pantalla rápida con mss + thumbnail con Pillow."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image


@dataclass
class Capture:
    png_b64: str
    thumb_b64: str
    width: int
    height: int


def _capture_pil() -> Image.Image:
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[1]
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
    # 1024px es buen balance: suficiente para que Gemini lea texto de UI, ~40-60% menos bytes que 1280px.
    full = _to_png_b64(img, max_side=1024)
    thumb = _to_png_b64(img, max_side=320)
    return Capture(png_b64=full, thumb_b64=thumb, width=w, height=h)
