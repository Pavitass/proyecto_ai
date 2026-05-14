# Helpdesk Agent — Loop visual agéntico + RAG rápido

Fecha: 2026-05-14
Estado: borrador para implementación
Alcance: entrega final (≤1 semana, macOS como SO de demo)

## 1. Objetivo

Elevar el agente de mesa de ayuda a un nivel "pro" para la entrega final con dos cambios mayores:

1. **Loop visual agéntico** — el agente toma capturas de pantalla, razona sobre lo que ve, ejecuta UNA acción de ratón/teclado con PyAutoGUI, verifica el resultado, y repite hasta cumplir el objetivo.
2. **RAG rápido y local por defecto** — top-k configurable, cache en memoria, embeddings locales, warm-up en arranque, y eliminación del fallback web automático.

Caso estrella de la demo: **enviar un correo desde Outlook web** con el agente conduciendo el navegador. Casos secundarios: ajustes de pantalla macOS, abrir/usar una app nativa (Outlook desktop o Teams). Windows se respeta a nivel de código pero no se demuestra en vivo.

## 2. No-objetivos

- No reescribir el agente de helpdesk existente (tickets, casos resueltos, escalado siguen igual).
- No añadir integraciones nuevas con APIs de Microsoft / Google (todo via UI).
- No soportar Windows en la demo (sí mantener compatibilidad de código existente).
- No hacer hardening completo de seguridad (es una entrega académica, no producción).

## 3. Arquitectura

```
helpdesk_app/
  vision_loop/                  ← NUEVO
    __init__.py
    loop.py                     ← orquestador (state machine)
    screen.py                   ← captura PNG + thumbnail/escala
    actor.py                    ← LLM visión → UNA acción JSON
    executor.py                 ← envoltura sobre desktop_exec_py
    events.py                   ← stream de eventos para SSE
  rag.py                        ← refactor: top-k param, cache, warm-up, MMR
  tools.py                      ← nueva tool `ejecutar_tarea_escritorio`
  graph.py                      ← system prompt sin fallback web automático
  main.py                       ← endpoint SSE + warm-up de RAG en startup
```

El loop visual se invoca como una tool de LangGraph. Mientras corre, emite eventos SSE que la UI (web + Electron) muestra en vivo.

## 4. Loop visual

### 4.1 Máquina de estados

```
INIT → CAPTURE → REASON → (CONFIRM si sensitive) → ACT → CAPTURE → … → DONE | FAIL | NEEDS_USER
```

Pseudocódigo:

```python
def run_loop(goal: str, max_steps=20, total_timeout_s=90):
    history = []  # últimos 3-4 (decision, thumb)
    t0 = time.time()
    for step in range(1, max_steps + 1):
        if time.time() - t0 > total_timeout_s:
            return STOP("timeout")
        img = screen.capture()                       # PNG, lado mayor ~1280px
        decision = actor.next_action(goal, img, history)
        emit("step", step, img_thumb=img, decision=decision)
        if decision.done:    return SUCCESS
        if decision.fail:    return STOP(decision.reason)
        if decision.needs_user: return STOP("needs_user", decision.reason)
        if decision.action.sensitive:
            ok = await user_confirm(decision)        # bloquea hasta UI responda
            if not ok: return STOP("user_canceled")
        executor.run(decision.action)
        history.append((decision, thumbnail(img)))
    return STOP("max_steps")
```

### 4.2 Schema de decisión (Pydantic)

```python
class LoopDecision(BaseModel):
    reasoning: str = Field(..., max_length=400)      # 1-3 frases
    action: DesktopAction | None                     # reutiliza schema actual
    done: bool = False
    fail: bool = False
    needs_user: bool = False
    reason: str = ""                                 # si done/fail/needs_user
```

`DesktopAction` se reutiliza tal cual de `desktop_plan.py` (move/click/type/hotkey/wait + flag `sensitive`).

### 4.3 Prompt del actor

System prompt en español, breve:

> Eres un agente que controla un escritorio paso a paso para cumplir un objetivo. Mira la captura. Decide UNA acción atómica que avance hacia el objetivo. Si ya está logrado, `done:true`. Si no puedes avanzar sin el usuario (contraseña, captcha, ambigüedad), `needs_user:true`. Si es imposible o peligroso, `fail:true`. NUNCA escribas contraseñas. Marca `sensitive:true` en envíos, borrados y ajustes del sistema. Responde JSON estricto.

El usuario del prompt: `goal + history corto (últimas 3 acciones) + imagen actual`.

Modelo: Gemini 2.x via `langchain-google-genai` (ya configurado en el proyecto).

### 4.4 Topes y seguridad

- `MAX_STEPS = 20` (configurable via env).
- `TOTAL_TIMEOUT_S = 90`.
- `pyautogui.FAILSAFE = True` (ya está) — esquina superior-izquierda aborta.
- Confirmación humana obligatoria si `action.sensitive == True`.
- Botón **Abortar** en UI siempre visible mientras el loop corre.
- Env gate `HELPDESK_DESKTOP_PY_EXEC=1` sigue siendo requisito (sin él, la tool devuelve error).
- Log de auditoría en `data/automation_log.jsonl` (timestamp, goal, step, action, hash de screenshot).

## 5. RAG

Cambios en `helpdesk_app/rag.py` y consumidores:

1. **Top-k parametrizable**: `buscar_contexto(consulta, k=4, mmr=False)`.
2. **Cache LRU** en memoria: `functools.lru_cache(maxsize=64)` sobre `(consulta_normalizada, k, mmr)`. Se invalida al reindexar (función `invalidate_cache()`).
3. **Embeddings locales por defecto**: si no hay `GOOGLE_API_KEY`, usar HF `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Si hay `GOOGLE_API_KEY`, mantener Google a menos que `HELPDESK_EMBEDDINGS=hf` esté seteado.
4. **Warm-up en startup**: `main.py` registra un `@app.on_event("startup")` que llama `get_vectorstore()` para forzar carga inicial (evita la latencia del primer query).
5. **MMR opcional**: parámetro `mmr=True` usa `max_marginal_relevance_search` para diversidad.
6. **System prompt actualizado** (`graph.py`): se elimina el fallback web automático. Web se llama solo cuando:
   - el usuario lo pide explícitamente, o
   - la KB devuelve 0 fragmentos relevantes (no "pocos" — exactamente cero).
   En ese caso el agente avisa antes ("voy a buscar en internet porque…").

Tool expuesta:

```python
@tool
def buscar_en_base_de_conocimiento(consulta: str, top_k: int = 4, diversidad: bool = False) -> str:
    ...
```

## 6. UI (web + Electron)

Reutilizar `helpdesk_app/static` y `electron/ui`. Añadir:

- **Panel "Automatización en vivo"** visible cuando hay un loop activo:
  - Header: `Paso N/MAX · ⏱ Ns · [Abortar]`
  - Miniatura de la última captura (max 320px).
  - Lista cronológica de pasos previos (icono de acción + texto del reasoning).
  - Texto del reasoning actual en grande.
- **Modal de confirmación** cuando llega un step con `sensitive=true`:
  - Captura full + descripción de acción + botones `Aprobar` / `Cancelar`.
- **Transporte**: SSE desde `GET /api/desktop/loop/stream?goal=…`. Eventos:
  - `step` `{n, max, thumb_b64, reasoning, action, sensitive}`
  - `confirm_required` `{n, full_b64, action, reasoning}`
  - `done` `{reason}`
  - `fail` `{reason}`
  - `aborted` `{reason}`
- **POST de respuesta a confirmación**: `POST /api/desktop/loop/confirm` `{run_id, step, approved}`.
- **POST de abort**: `POST /api/desktop/loop/abort` `{run_id}`.

## 7. Cambios al system prompt del agente helpdesk

En `graph.py`:

- Quitar el bullet "si la KB queda floja, llama `buscar_en_web`".
- Añadir: "Web solo cuando el usuario la pida o cuando la KB devuelva cero resultados; avisa antes."
- Añadir bullet sobre `ejecutar_tarea_escritorio`: "Solo si el usuario pide explícitamente que hagas algo en su equipo. Antes de invocar, resume en lenguaje natural lo que vas a intentar y advierte que cada paso sensible requiere su aprobación."

## 8. Seguridad

- Gate de env var `HELPDESK_DESKTOP_PY_EXEC=1` para activar ejecución real.
- Confirmación humana en acciones `sensitive`.
- Prohibición explícita en prompt: nunca escribir contraseñas; si la UI las pide, `needs_user:true`.
- Topes duros de pasos y tiempo.
- FAILSAFE PyAutoGUI activo.
- Log de auditoría (`data/automation_log.jsonl`).
- Allow-list implícita: la tool solo se ofrece al LLM si el goal vino de una petición explícita del usuario (validación en el agente vía prompt + heurística simple en `tools.py`).

## 9. Testing y demo

- **Smoke test** del loop: goal "abre Spotlight y escribe 'calculadora'" — para verificar permisos de macOS antes de cada demo.
- **Unit tests RAG**: cache funciona (segundo query no re-embed), `k` respeta tamaño, `mmr=True` cambia orden vs `mmr=False`.
- **`docs/demo-checklist.md`**: pasos exactos del día (qué decir, qué esperar, plan B si Outlook cambia layout o pide login).
- **Permisos macOS**: documentar en README que Electron/Terminal/Python necesitan "Accesibilidad" + "Grabación de pantalla" en Ajustes del Sistema.

## 10. Plan de entrega

Orden sugerido (la fase siguiente — `writing-plans` — lo detallará paso a paso):

1. Refactor RAG (top-k, cache, embeddings locales por defecto, warm-up). **[gana velocidad inmediata, sin tocar UI]**
2. Quitar fallback web del system prompt. Test rápido conversacional.
3. Esqueleto del módulo `vision_loop/` (screen + executor reusando lo existente).
4. Actor LLM visión + schema + prompt. Test offline con captura fija.
5. Orquestador loop.py con state machine + topes.
6. SSE endpoint + tool LangGraph.
7. UI panel "Automatización en vivo" + modal confirmación.
8. Pulido caso estrella Outlook web (probar 5-10 veces, ajustar prompt del actor).
9. Smoke tests + demo-checklist.md + README permisos.

## 11. Riesgos

- **Outlook web cambia layout** entre desarrollo y demo: el loop visual es robusto a esto si el actor sabe identificar "Nuevo correo" por texto, no por coordenadas fijas. Plan B en el checklist.
- **Permisos macOS revocados**: smoke test antes de la demo lo detecta.
- **Latencia visión**: ~2-4s por paso con Gemini. Aceptable en demo, pero hay que enseñar el "pensando…" para que no parezca colgado.
- **El LLM bucla**: el tope de `MAX_STEPS` lo corta; el reasoning queda en el log.
