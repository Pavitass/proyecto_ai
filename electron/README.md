# App de escritorio (Electron)

## Qué hace
- Ventana **Electron** que carga la **misma URL** que el navegador (`HELPDESK_URL`, por defecto `http://127.0.0.1:8787`): chat, tickets y panel **Control del escritorio**.
- Ejecuta planes JSON (`move`, `click`, `wait`, `type`, `hotkey`) con **`@nut-tree-fork/nut-js`** en la máquina del usuario.

## Alternativa: PyAutoGUI (Python)
Si no usas Electron pero el servidor FastAPI corre **en tu propio PC** y abres la web en **localhost**, puedes ejecutar pasos con **PyAutoGUI** vía `POST /api/desktop/exec` (activar `HELPDESK_DESKTOP_PY_EXEC=1`). El ratón se mueve **donde corre uvicorn**, no en un cliente remoto.

## Human-in-the-loop
- El plan puede marcar pasos con **`"sensitive": true`** (ajustes del sistema, interruptores, etc.). En **Electron** se pide **confirm()** antes de ejecutarlos (salvo YOLO con opción explícita para sensibles).
- Con **PyAutoGUI**, el servidor exige **`human_ack: true`** en el JSON para pasos sensibles (o para **todos** los pasos si defines `HELPDESK_DESKTOP_FORCE_ACK=1`). La interfaz incluye una casilla de confirmación.

## Arranque
1. Terminal A, en `helpdesk_agent`: `python3 run.py`
2. Terminal B, en `helpdesk_agent/electron`: `npm install` (una vez) y `npm start`

Variables: `HELPDESK_URL`, `HELPDESK_THREAD_ID`, `HELPDESK_ELECTRON_PAGE=widget` (mini ventana).

## Permisos (macOS)
**Ajustes → Privacidad y seguridad → Accesibilidad** para **`Electron.app`** (suele ser `node_modules/electron/dist/Electron.app`). Sin eso, `nut-js` mostrará avisos y no moverá el ratón.

## Límites
- Coordenadas **0–1** son aproximadas; multi‑monitor puede desalinear.
- PyAutoGUI en servidor remoto **no** automatiza el PC del usuario (solo el host del API).
