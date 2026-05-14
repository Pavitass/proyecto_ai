#!/bin/bash
# Doble clic: app de escritorio nativa (Electron) — plan de ratón/teclado y ejecución con aprobación o YOLO.
# Antes: en otra terminal `python run.py` en esta carpeta (motor API en HELPDESK_URL).
# Otro puerto: export HELPDESK_URL=http://127.0.0.1:PUERTO
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/electron"
export HELPDESK_URL="${HELPDESK_URL:-http://127.0.0.1:8787}"
if [[ ! -d node_modules ]]; then
  echo "Instalando dependencias de Electron (npm install)…"
  npm install
fi
exec npm start
