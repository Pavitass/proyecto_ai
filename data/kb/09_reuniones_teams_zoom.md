# Reuniones: Teams, Zoom y periféricos

## Microsoft Teams (Windows y Mac)
- **No se oye / no hay audio**: comprobar dispositivo de salida en Teams y en el sistema; salir y volver a la reunión; Teams → **Configuración → Dispositivos** → prueba de altavoz y micrófono.
- **Cámara negra**: otro programa usando la cámara (cerrar otras apps de videollamada); permisos de cámara en el sistema operativo; reiniciar Teams.
- **Pantalla compartida falla**: permisos de **grabación de pantalla** (macOS) o políticas de DLP en Windows; probar compartir solo una ventana en lugar de pantalla completa.
- **Calidad mala**: cable Ethernet si es posible; desactivar cámara si la red es muy limitada; cerrar descargas pesadas en segundo plano.

## Zoom
- **Código de error al unirse**: anotar número exacto; revisar firewall/proxy corporativo (puertos documentados por Zoom).
- **Actualización obligatoria**: instalar desde portal corporativo o sitio oficial; no enlaces de terceros.
- **Virtual background que no funciona**: requisitos de CPU/GPU; en Mac, permisos de cámara; fondos personalizados pueden estar deshabilitados por política.

## Navegador vs aplicación de escritorio
- Teams en **navegador** puede tener menos funciones (compartir pantalla, breakout rooms) según versión y permisos del navegador.
- Si la empresa estandariza la app de escritorio, orientar al usuario a esa vía para incidencias recurrentes.

## Salas y hardware de reunión
- **Barra de video / micrófono de sala**: reinicio controlado del dispositivo; comprobar HDMI/USB‑C seleccionado como fuente en pantalla.
- **Eco**: un portátil con micrófono y altavoz abiertos cerca del sistema de sala; silenciar uno de los dos.

## Escalado
Problemas de **certificados SSL**, **SSO** o **acceso guest bloqueado** suelen requerir identidad corporativa o cambios en tenant; documentar hora (UTC), ID de reunión y mensaje de error textual.
