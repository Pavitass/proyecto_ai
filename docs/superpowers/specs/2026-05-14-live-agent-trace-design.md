# Live Agent Trace — mostrar en vivo qué hace la IA

Fecha: 2026-05-14
Estado: borrador para implementación
Alcance: vista en vivo de la actividad del agente durante cada turno (tools, fuentes, tickets, fases).

## 1. Objetivo

Sustituir la `thinkingCard` actual (labels fijos) por un **timeline en vivo** que muestre, conforme ocurren:
- Fase del turno (analizando / llamando tool / componiendo / hecho).
- Cada tool con argumento corto y resultado breve.
- Cada fragmento KB consultado (archivo + preview).
- Cada resultado web (título + URL).
- Cada operación de ticket (crear / actualizar / resolver / escalar).

Al terminar, la tarjeta se colapsa automáticamente y queda accesible como botón "Ver actividad" bajo la respuesta del asistente.

## 2. No-objetivos

- No streamear el texto-token del LLM (overkill para esta entrega).
- No mostrar el cuerpo completo del tool_result (puede ser MB).
- No persistir el trace entre sesiones (en memoria por thread, vive con el proceso).

## 3. Arquitectura

```
helpdesk_app/
  agent_trace.py             ← NUEVO: registro por thread + bus de eventos
  tools.py                   ← Modificado: emite events por cada tool / KB / web / ticket
  main.py                    ← Modificado: endpoint SSE /api/agent/trace/{thread_id}; emit phase
  static/agent_trace.js      ← NUEVO: cliente SSE + render del timeline
  templates/index.html       ← Modificado: rehacer thinkingCard body
  static/app.css             ← Modificado: estilos timeline
```

## 4. agent_trace.py

```python
# Estructuras: por thread_id → lista de runs (cada turno = run), cada run = lista de eventos.
# Run actual identificado por turn_id (uuid corto).
@dataclass
class TraceRun:
    turn_id: str
    started_at: float
    finished: bool
    event_queue: queue.Queue
    events_history: list[dict]    # para que el cliente que conecta tarde rehidrate

API:
- begin_turn(thread_id) -> TraceRun           # crea run, emite phase:started
- end_turn(turn_id)                            # marca finished, emite phase:done
- emit(thread_id, type, payload)               # añade a event_queue y history del run actual
- get_run(turn_id) -> TraceRun | None
- get_active_run(thread_id) -> TraceRun | None
```

Eventos:
```
{type: "phase",       phase: "analyzing"|"tool_calling"|"composing"|"done"}
{type: "tool_start",  name: "buscar_en_base_de_conocimiento", args_preview: "vpn no conecta"}
{type: "tool_end",    name: "...", ok: true, summary: "3 fragmentos"}
{type: "kb_hit",      source: "02_vpn_acceso_remoto.md", preview: "Configuración VPN…"}
{type: "web_hit",     title: "…", url: "…", snippet: "…"}
{type: "ticket_op",   op: "crear"|"actualizar"|"resolver"|"escalar", ticket_id: "abc", titulo: "…"}
{type: "stats",       duration_ms: 2300, tool_calls: 3, kb_hits: 4, web_hits: 0}
```

## 5. Integración con tools.py

Cada tool envuelve su lógica con `emit("tool_start", ...)` al entrar y `emit("tool_end", ...)` al salir. RAG-helper (`buscar_contexto`) emite `kb_hit` por cada doc (sin tocar `buscar_contexto` directamente — lo hace la tool `buscar_en_base_de_conocimiento` que es la que ya itera los docs). Web search igual. Ticket ops idem.

`chat_trace` queda como está (compatibilidad con el panel viejo `attachSourcesToolsPanel`).

## 6. main.py — hook al turn

En `/api/chat`:

```python
turn = agent_trace.begin_turn(body.thread_id)
try:
    agent_trace.emit(thread_id, "phase", {"phase": "analyzing"})
    # ... graph.invoke(...) ...
    agent_trace.emit(thread_id, "phase", {"phase": "composing"})
    # ... build response ...
    agent_trace.emit(thread_id, "stats", {"duration_ms": ..., "tool_calls": len(...), ...})
finally:
    agent_trace.end_turn(turn.turn_id)
```

Endpoint SSE:

```python
GET /api/agent/trace/{turn_id}    # stream eventos hasta phase:done
```

El cliente recibe la lista `events_history` primero (rehidratación si llegó tarde) y luego eventos vivos.

## 7. Frontend — thinkingCard rehecho

Reemplazar el contenido HTML actual de `#thinkingCard` por:

```html
<div class="thinking-head">
  <span class="spinner"></span>
  <span id="thinkingPhaseLabel">Analizando…</span>
  <span class="thinking-stats" id="thinkingStats"></span>
</div>
<ol class="trace-timeline" id="traceTimeline"></ol>
```

`agent_trace.js`:

```js
window.helpdeskAttachTrace = function(turnId, mountEl) {
  // open EventSource /api/agent/trace/{turnId}
  // for each event, append a <li> with icon + text
  // on phase:done, set finished flag, mountEl.dataset.finished = "1"
};
```

Render por tipo:
- `phase:analyzing` → header label "Analizando tu mensaje…".
- `tool_start` → "🔍 `name` (`args_preview`)".
- `tool_end` → marca la última `tool_start` con su mismo `name` como completada (verde) y añade `summary`.
- `kb_hit` → línea indentada con 📄 `source` — preview corto.
- `web_hit` → 🌐 `title` (link).
- `ticket_op` → 🎫 `op` ticket `id` — `titulo`.
- `phase:composing` → header label "Componiendo respuesta…".
- `phase:done` + `stats` → header label "✅ Hecho · 2.3s · 3 KB · 1 ticket", auto-colapsa después de 1.5s.

Después de colapsar, queda un botón pequeño bajo la respuesta: **▸ Ver actividad del agente** que reabre el timeline.

## 8. Toggle "Mostrar actividad del agente"

Checkbox en la cabecera (`.top-actions`) con texto "Modo demo: actividad visible". Si está ON, el timeline NO se auto-colapsa al terminar. Estado en `localStorage`.

## 9. Wiring entre /api/chat y /api/agent/trace

El cliente al enviar mensaje:
1. POST a `/api/chat` con `body`.
2. **En paralelo**, lee `Set-Cookie` o respuesta inicial — necesitamos pasar el `turn_id` al frontend antes de que termine el chat para abrir el SSE.

Como `/api/chat` es síncrono (no streaming), aproximamos:
- Genera el `turn_id` **en el cliente** (uuid) y pásalo en el body como `turn_id?: str`.
- El backend usa ese `turn_id` (o genera uno si viene vacío) y lo devuelve en la respuesta.
- Al frontend le sirve para abrir SSE inmediatamente con el id conocido.

Backend acepta `body.turn_id`, lo registra como key del run, mete a la queue.

Si el cliente abre SSE **antes** de que el backend cree el run → el endpoint espera unos ms o devuelve 404 → cliente reintenta. Mejor: backend acepta crear el run vacío en el primer GET y poblar después (lazy registry).

## 10. Riesgos

- **El run termina antes de que el cliente conecte**: rehidratación con `events_history` resuelve.
- **Múltiples runs en paralelo del mismo thread**: imposible (un turno a la vez por thread).
- **Memoria**: cada run guarda eventos en lista — limitamos a 200 eventos/run, descartando los más viejos si excede. Limpieza de runs > 5 min terminados.

## 11. Plan de entrega

1. `agent_trace.py` + tests unitarios.
2. SSE endpoint + lazy registry de runs.
3. Instrumentación en `tools.py` (cada tool).
4. Hook `/api/chat` con begin/end turn.
5. Frontend `agent_trace.js` + thinkingCard rehecho.
6. Toggle "modo demo".
7. Smoke E2E.
