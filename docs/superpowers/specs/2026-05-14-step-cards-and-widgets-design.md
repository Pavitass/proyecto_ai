# Step-cards inline + endpoint ligero + helpdesk-ui ampliado

Fecha: 2026-05-14
Estado: borrador para implementación
Alcance: mejorar UX paso-a-paso del helpdesk (caso de uso real, no el loop visual) + widgets interactivos generados por la IA.

## 1. Objetivo

Hoy cada interacción mínima con los pasos del agente (marcar checkbox, "Me atasco") dispara una regeneración completa de la respuesta por el LLM (~5-20s, ruido en el chat). Queremos:

1. **Marcar paso como hecho** sea instantáneo y silencioso (no llama al LLM).
2. **Marcar paso como atascado** sea inline, con texto + captura opcional, y dispare al LLM con contexto preciso.
3. La IA pueda generar **widgets interactivos** además del markdown (selección única, gravedad), para acelerar el diagnóstico.

## 2. No-objetivos

- No tocar el loop visual agéntico (Outlook web, etc.) — es otra feature.
- No persistir el estado de los pasos en disco (memoria del thread es suficiente).
- No reescribir el chat completo — vamos por encima de lo que hay.

## 3. Arquitectura

```
helpdesk_app/
  step_state.py                ← NUEVO: estado de pasos por thread (in-memory)
  main.py                      ← NUEVO endpoint POST /api/steps/update + GET /api/steps/{thread}
  templates/index.html         ← Render de step-cards + UI atasco + widgets
  static/app.css               ← Estilos de step-cards + widgets
  static/step_cards.js         ← NUEVO: detector + render de pasos como tarjetas
  static/widgets.js            ← NUEVO: render de bloques helpdesk-ui ampliado (choice, severity)
  interactive_block.py         ← Ampliar para reconocer choice y severity en el JSON
  graph.py                     ← Prompt: cuándo usar choice / severity + flujo step_failed
```

## 4. Estado de pasos (backend)

### 4.1 `step_state.py` (nuevo)

Diccionario `thread_id -> { message_id -> [ {index, text, status, note} ] }` en memoria, con lock. `status` ∈ `pending | done | stuck`. No persistencia (vive lo que vive el proceso).

API mínima:
```python
def upsert_steps(thread_id, message_id, steps: list[dict]) -> None
def update_step(thread_id, message_id, index, status, note="") -> bool
def get_steps(thread_id) -> dict[str, list[dict]]   # all messages
def clear_thread(thread_id) -> None
```

### 4.2 Endpoints en `main.py`

- `POST /api/steps/update` `{thread_id, message_id, index, status, note?}` → `{ok}`
- `GET /api/steps/{thread_id}` → `{messages: {<msg_id>: [...]}}` (para rehidratar al cargar)
- `POST /api/steps/register` `{thread_id, message_id, steps: [{index,text}]}` → `{ok}` (el frontend llama al detectar pasos en una respuesta)

Sin llamadas al LLM. Devuelven en < 10ms.

### 4.3 Inyección al chat

En el `/api/chat` actual, **antes de pasar el historial al grafo**, prependear a la última `HumanMessage` un bloque oculto con el estado del thread:

```
[Estado de pasos]
Mensaje msg-3: 1✓, 2✓, 3▶, 4◯
Mensaje msg-7: 1✕ (atasco: "no aparece el botón Enviar")
```

Eso le da al LLM el contexto sin que el usuario tenga que escribir nada. Cuando el usuario pide "siguiente paso" o "ayúdame con esto", el LLM ya sabe en qué está atascado.

## 5. Frontend — Step-cards

### 5.1 Detector

Al renderizar una burbuja del asistente, escanear su markdown por:
- Una lista ordenada (`<ol>`) bajo un heading "Plan de acción" (caso normal).
- O bien tareas GFM (`<input type=checkbox>` en `<li>`).

Para cada paso encontrado se genera:
- Un `data-msg-id` (único por respuesta, ej. `crypto.randomUUID()`).
- Un array de `{index, text}` que se POST-ea a `/api/steps/register`.
- El `<ol>` original se **reemplaza por un contenedor de tarjetas**:

```html
<div class="step-cards" data-msg-id="…">
  <div class="step-card" data-index="0" data-status="pending">
    <div class="step-head">
      <span class="step-num">1</span>
      <span class="step-status-icon">◯</span>
      <span class="step-text">Abre Outlook web…</span>
    </div>
    <div class="step-actions">
      <button class="btn-done">✓ Hecho</button>
      <button class="btn-stuck">✕ Atascado</button>
      <button class="btn-shot">📷 Captura</button>
    </div>
    <div class="step-stuck-form" hidden>
      <textarea placeholder="¿Qué pasa?"></textarea>
      <div class="step-stuck-actions">
        <button class="btn-stuck-shot">📷 Adjuntar captura</button>
        <button class="btn-stuck-send">Enviar al agente</button>
        <button class="btn-stuck-cancel">Cancelar</button>
      </div>
    </div>
  </div>
  …
</div>
<div class="step-cards-footer">
  <button class="btn-feedback">📨 Pedir comentario al agente</button>
</div>
```

### 5.2 Estados visuales

- `pending` ◯ — borde gris, texto normal.
- `current` ▶ — borde azul + sombra suave + scrolled into view. Solo una `current` a la vez por bloque.
- `done` ✓ — fondo verde tenue, texto tachado suave, icono verde.
- `stuck` ✕ — borde rojo, expandido con el `note`.

La "current" es automática: la primera `pending` después de la última `done`.

### 5.3 Comportamiento

- **Click "✓ Hecho"**: POST silencioso `/api/steps/update` → tarjeta pasa a `done`, siguiente `pending` se vuelve `current`. Sin LLM.
- **Click "✕ Atascado"**: expande `step-stuck-form`. Al pulsar "Enviar al agente":
  1. POST `/api/steps/update` con `status=stuck, note=<texto>`.
  2. Compone mensaje al chat: `[Paso N atascado] "<texto del paso>"\nLo que veo: <nota>\n` + adjunta captura si existe.
  3. Envía vía el flujo de chat existente (`liveSheetChat`). Eso sí dispara al LLM, **pero con contexto preciso**.
- **Click "📷 Captura"**: reusa el botón existente de captura (`btnShotScreen`) y precarga `[Paso N] ` en el textarea como prefijo.
- **Click "📨 Pedir comentario"**: envía un mensaje corto `[Estado de pasos actualizado] revisa progreso y dame el siguiente micro-paso si aplica`. Esto sí va al LLM.

### 5.4 Rehidratación

Al cargar el chat o al recargar página, el frontend llama `GET /api/steps/{thread_id}` y aplica los estados a las tarjetas presentes. Si una respuesta del asistente ya no está en el DOM (porque fue truncada), su estado queda obsoleto y se ignora.

## 6. Widgets interactivos — extensión `helpdesk-ui`

`interactive_block.py` hoy reconoce JSON con `kanban` y `sliders`. Ampliamos a:

### 6.1 `choice` (opción única)

```json
{
  "choice": {
    "id": "err",
    "prompt": "¿Qué mensaje de error aparece?",
    "options": [
      {"id": "a", "label": "No hay conexión a Internet"},
      {"id": "b", "label": "Certificado inválido"},
      {"id": "c", "label": "Ninguno de los anteriores"}
    ]
  }
}
```

Render: card con prompt + lista de botones radio-style. Al pulsar uno, envía al chat:
```
[choice err] "Certificado inválido"
```
Esto **sí** llama al LLM (con contexto preciso para refinar).

### 6.2 `severity` (slider semántico)

```json
{
  "severity": {
    "id": "imp",
    "prompt": "¿Cuánto te bloquea esto ahora mismo?",
    "labels": ["Solo molesto", "Lento pero funciono", "A medias", "Sin trabajar", "Toda mi tarea bloqueada"]
  }
}
```

Render: slider 1-5 con etiquetas semánticas. Cambio de valor = POST silencioso al endpoint `/api/steps/update` (reusamos el endpoint con un campo extra `severity`). No llama al LLM. El valor se inyecta al estado del thread y el LLM lo lee en el siguiente turno.

### 6.3 Prompt al LLM

Añadir al `SYSTEM_PROMPT` en `graph.py`, en la sección del bloque `helpdesk-ui`:

> Además de `kanban` y `sliders`, puedes generar:
> - **`choice`** (opción única) cuando convenga acotar el diagnóstico con 2-5 opciones excluyentes. No uses `choice` si la pregunta es abierta.
> - **`severity`** (gravedad 1-5 con etiquetas semánticas) al abrir un ticket, para captar prioridad real sin preguntar tres veces.

## 7. Modo guiado existente

Compatibilidad: la barra `guidedBar` actual queda **opcional**. Las step-cards la sustituyen para la mayoría de casos, pero el botón "Guiado" sigue funcionando para usuarios que prefieran la barra arriba. Internamente, la barra se sincroniza con el estado de step-cards (lee el mismo data structure).

## 8. Manejo de errores

- POST `/api/steps/update` falla → revertir el estado visual en el cliente, mostrar toast pequeño "No se pudo guardar".
- Network drop durante "atascado" → mantener el form abierto con el texto del usuario, botón "Reintentar".
- Mensaje sin pasos detectados → no se inyecta nada, comportamiento actual intacto.

## 9. Testing

- Unit (Python): `step_state.upsert_steps/update_step/get_steps` con lock, eviction si `thread_id` no existe.
- Smoke manual: marcar 2 pasos hechos, ver que el siguiente se marca current; marcar atascado, ver mensaje preciso enviado.
- Widget `choice`: el LLM (con prompt actualizado) genera el bloque; el front lo renderiza; click envía mensaje formado.

## 10. Plan de entrega (orden)

1. `step_state.py` + endpoints + tests.
2. Inyección de estado al `/api/chat` (sin tocar el grafo).
3. Frontend `step_cards.js` + CSS (sin widgets nuevos todavía).
4. Botón "📨 Pedir comentario".
5. Ampliar `interactive_block.py` para `choice` y `severity`.
6. `widgets.js` con render de los 2 nuevos.
7. Actualizar `SYSTEM_PROMPT` para que el LLM use los nuevos widgets.
8. Smoke E2E manual.

## 11. Riesgos

- **El LLM ignora el bloque `[Estado de pasos]`** que prependeamos: mitigamos diciéndolo en el system prompt.
- **El LLM repite pasos ya marcados como hechos**: el prompt debe instruir "no rehagas pasos que el usuario ya marcó como ✓".
- **Detección de pasos frágil**: nos basamos en heading "Plan de acción" + `<ol>` o GFM tasks; si el LLM cambia el formato, no aparecen tarjetas. Mitigación: el system prompt YA exige ese formato; lo reforzamos.
- **Widgets choice con muchas opciones**: limitamos a 5 max para no romper layout.
