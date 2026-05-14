#!/usr/bin/env python3
"""Arranque local: desde la carpeta helpdesk_agent ejecuta `python3 run.py` (o `./run.py` si el fichero es ejecutable).

En macOS el comando `python` suele no existir. Con el venv en la raíz del repo (IA_WORKSHOPS):
`../.venv/bin/python3 run.py` desde esta carpeta; o activa el venv y ejecuta `python3 run.py`.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("HELPDESK_PORT", "8787"))
    uvicorn.run(
        "helpdesk_app.main:app",
        host="127.0.0.1",
        port=port,
        reload=True,
        reload_dirs=[str(ROOT / "helpdesk_app")],
    )
