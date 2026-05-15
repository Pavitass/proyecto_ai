# Tickets ligados a conversación + UI tabs/detalle

Fecha: 2026-05-14
Estado: borrador para implementación
Alcance: vincular tickets al `thread_id` de la conversación, dos pestañas en la barra lateral, panel de detalle.

## 1. Objetivo

1. Cada ticket creado durante una conversación queda asociado a su `thread_id`.
2. La barra lateral muestra dos pestañas: **Esta conversación** y **Todos**.
3. Click en un ticket abre un **panel de detalle** con título, descripción, prioridad (chip de color), categoría, estado, pasos sugeridos y un botón **Continuar en chat** que enfoca el input y precarga `[Ticket #abc] `.

## 2. No-objetivos

- No reescribir el flujo del agente para crear tickets — `crear_ticket_de_servicio` ya existe y se reusa.
- No persistir tickets retroactivamente con thread_id (los anteriores quedan con thread_id = NULL → visibles solo en "Todos").
- No editar tickets desde la UI (eso ya lo hace el agente vía `actualizar_ticket_de_servicio`).

## 3. Arquitectura

```
helpdesk_app/
  db.py                        ← MIGRAR: añadir columna thread_id, helpers para filtrar
  tools.py                     ← `crear_ticket_de_servicio` recibe thread_id implícito vía contextvar
  chat_context.py              ← NUEVO contextvar `chat_thread_id` (similar al existente `chat_client_os`)
  main.py                      ← /api/tickets ya existe; añadir filtro ?thread_id=...; setear contextvar en /api/chat
  templates/index.html         ← UI: tabs + panel de detalle
  static/app.css               ← Estilos de tabs, chips de prioridad, modal de detalle
```

## 4. Esquema SQLite — migración

Añadir columna `thread_id TEXT` a la tabla `tickets`. La migración va en `_migrate_tickets_schema()` (patrón ya establecido en el archivo). Tickets antiguos: `thread_id = NULL`.

Índice opcional: `CREATE INDEX IF NOT EXISTS idx_tickets_thread ON tickets(thread_id)`.

## 5. Backend

### 5.1 `chat_context.py`

Añadir:
```python
chat_thread_id: ContextVar[str] = ContextVar("chat_thread_id", default="")
```

### 5.2 `main.py` — setear contextvar al inicio de `/api/chat`

```python
token_thread = chat_ctx.chat_thread_id.set(body.thread_id)
try:
    ...  # existing chat logic
finally:
    chat_ctx.chat_thread_id.reset(token_thread)
```

### 5.3 `db.crear_ticket` — aceptar `thread_id` opcional

```python
def crear_ticket(..., thread_id: str | None = None) -> str:
```

Insertar `thread_id` (puede ser `None`). Mantener compatibilidad con llamadas existentes.

### 5.4 `tools.crear_ticket_de_servicio` — leer contextvar

Dentro de la tool, leer `chat_ctx.chat_thread_id.get()` y pasarlo a `db.crear_ticket`. El LLM no necesita saberlo (no añadimos un parámetro a la tool signature, así no rompemos el prompt actual).

### 5.5 `/api/tickets` — filtro opcional

`GET /api/tickets?thread_id=<id>` → filtra. Sin parámetro = comportamiento actual (todos).

Devolver lista ordenada por `created_at DESC`.

### 5.6 `/api/tickets/{id}` (puede ya existir)

Verificar si ya hay endpoint de detalle; si no, añadirlo. Devuelve el ticket completo.

## 6. Frontend

### 6.1 Tabs en la barra lateral

Reemplazar el bloque `TICKETS RECIENTES` por:

```html
<div class="panel" id="ticketsPanel">
  <div class="tickets-tabs">
    <button class="tab-btn active" data-scope="thread">Esta conversación</button>
    <button class="tab-btn" data-scope="all">Todos</button>
  </div>
  <div class="tickets" id="ticketsList"></div>
</div>
```

JS: una función `loadTickets(scope)`:
- `scope="thread"` → `GET /api/tickets?thread_id=<window.__HELPDESK_THREAD_ID__>`
- `scope="all"` → `GET /api/tickets`

Al cambiar de thread (nuevo botón "Nueva sesión"), se refresca la lista de la pestaña activa.

### 6.2 Card mejorada

Cada ticket muestra:
- Título (en negrita).
- Chip de prioridad (`alta` rojo, `media` ámbar, `baja` gris).
- Chip de categoría (gris claro).
- Estado pequeño (texto).
- ID corto (`abc123…`).

### 6.3 Panel de detalle (modal)

Click en card → abre modal con:
- Título grande
- Chips: prioridad, categoría, estado, ID copiable
- Descripción del usuario (renderizada con saltos de línea preservados)
- Pasos sugeridos (renderizado markdown si es posible)
- Fuentes KB (lista)
- Fechas: creado, resuelto (si aplica)
- Resolución final (si existe)
- Botones: **Cerrar** · **Continuar en chat** (precarga `[Ticket abc123…] ` en el textarea y cierra modal)

## 7. System prompt

No requiere cambios — el agente ya crea tickets proactivamente. El `thread_id` se inyecta de forma transparente.

## 8. Testing

- Unit Python: nueva columna se crea por migración en una BD vacía; `crear_ticket(thread_id=...)` persiste el valor; `obtener_tickets_por_thread(thread_id)` filtra correctamente.
- Smoke API: POST hipotético crea ticket, GET con thread_id devuelve solo ese; GET sin filtro devuelve todos.
- Manual UI: cambiar de pestaña; abrir detalle; click en "Continuar en chat".

## 9. Riesgos

- **BD existente con tickets sin thread_id**: visibles solo en pestaña "Todos". Aceptable.
- **Reload de página**: `window.__HELPDESK_THREAD_ID__` se rehidrata desde localStorage (ya existe esa lógica). Si el thread_id cambia, la pestaña "Esta conversación" cambia también.
- **Contextvar y async**: FastAPI handlers son `def` (síncronos) en este proyecto, así que `ContextVar` funciona sin issues.

## 10. Orden de implementación

1. Migración SQLite + actualizar `crear_ticket` y helpers.
2. Contextvar + cableado en `/api/chat` y `crear_ticket_de_servicio`.
3. Endpoint `/api/tickets?thread_id=` con filtro.
4. UI: tabs + nueva card.
5. UI: modal de detalle con "Continuar en chat".
6. Smoke E2E.
