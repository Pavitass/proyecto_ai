# Demo Checklist — Mesa de ayuda TI (entrega final)

## 1 hora antes
- [ ] Vaciar `data/automation_log.jsonl` (mover a `.bak`).
- [ ] `HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 run.py` y abrir Electron.
- [ ] **Smoke test del loop**: "abre Spotlight y escribe calculadora" → debe verse cursor moverse, captura cambiar y al final Spotlight con "calculadora".
- [ ] Verificar permisos macOS: System Settings → Privacy & Security → Accesibilidad y Grabación de pantalla incluyen Python/Electron.

## Demo Outlook web (caso estrella)
- [ ] Abrir Outlook web manualmente en Safari/Chrome, login hecho, bandeja vacía de drafts.
- [ ] En el chat: "envíame un correo a <destino> con asunto 'Demo' y cuerpo corto. Hazlo tú en mi Outlook web."
- [ ] Verificar: panel aparece, cursor se mueve, captura va cambiando, modal de confirmación al pulsar **Enviar**.
- [ ] **Plan B**: si Outlook pide login o cambia el layout — el actor debe devolver `needs_user` (la UI lo mostrará). Comentarlo como característica.

## Demo RAG rápido
- [ ] Pregunta: "mi VPN no conecta, qué hago" → debe responder en < 3s sin tocar la web.
- [ ] Pregunta: "busca en internet la versión última de Cisco AnyConnect" → debe avisar antes de ir a web.

## Demo step-cards
- [ ] En el chat: "Mi VPN no conecta."
- [ ] Las opciones del plan deben aparecer como tarjetas (no lista numerada plana).
- [ ] Marcar paso 1 como ✓ — debe ser instantáneo (sin nuevo turno del LLM).
- [ ] Marcar paso 2 como ✕ Atascado con nota corta — el LLM responde con `### Ajuste al paso 2`.
- [ ] Si el LLM emite `choice` o `severity`, el widget aparece debajo del mensaje y es interactivo.

## Demo tickets por conversación
- [ ] Iniciar nueva sesión.
- [ ] Describir incidencia: "Mi VPN no conecta con error de certificado". El agente debe crear un ticket.
- [ ] Pestaña "Esta conversación" en la barra lateral debe mostrarlo; "Todos" muestra también los previos.
- [ ] Click en el ticket abre modal con título, prioridad coloreada, descripción y pasos sugeridos.
- [ ] Botón "Continuar en chat" precarga `[Ticket abc12345] ` en el textarea.

## Cierre
- [ ] Mostrar `data/automation_log.jsonl` (transparencia: cada paso queda registrado).
- [ ] Mostrar `data/tickets.sqlite3` con el ticket creado durante la sesión.

## Demo actividad del agente en vivo
- [ ] Activar **Modo demo** en la cabecera (checkbox).
- [ ] Preguntar "Mi VPN no conecta con certificado expirado".
- [ ] Mientras el agente piensa, debe verse en vivo:
  - 🔧 buscar_en_base_de_conocimiento ("vpn no conecta")
  - 📄 02_vpn_acceso_remoto.md — preview
  - 📄 04_red_wifi.md — preview
  - 🎫 crear ticket abc12345 — VPN no conecta
- [ ] Al final: "✓ Hecho · 2.3s · 3 tools · 5 KB".
- [ ] Sin Modo demo, la tarjeta se colapsa sola tras 1.5s y queda accesible con `▾`.
