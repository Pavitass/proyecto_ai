## Permisos macOS para el loop visual

El loop agéntico necesita:

1. **Accesibilidad** (mover ratón / teclado): Ajustes del Sistema → Privacidad y seguridad → Accesibilidad. Añadir Python (o el binario que ejecute uvicorn) **y** Electron (si usas el cliente).
2. **Grabación de pantalla** (capturas): misma ruta, sección "Grabación de pantalla". Añadir Python y Electron.
3. Reiniciar el proceso después de conceder permisos.

Variable de entorno requerida para activar la ejecución:

```bash
export HELPDESK_DESKTOP_PY_EXEC=1
```

Sin ella, el agente devuelve `gate_disabled` y nunca toca el ratón.
