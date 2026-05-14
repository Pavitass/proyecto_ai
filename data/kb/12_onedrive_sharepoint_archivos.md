# OneDrive, SharePoint y archivos en la nube (orientación mesa de ayuda)

## OneDrive (Windows)
- **Icono con triángulo o error de sincronización**: clic en el icono → Ver problemas; **Reanudar sincronización**; si persiste, **Restablecer** OneDrive (comando oficial `onedrive.exe /reset` en rutas documentadas por Microsoft) con precaución y backup.
- **Archivos “solo en la nube”**: necesitan conexión para abrir; “Mantener siempre en este dispositivo” para trabajo offline.
- **Conflicto de versión**: abrir ambas copias desde la web de OneDrive y fusionar manualmente si la app no resuelve.

## OneDrive (macOS)
- Comprobar **ubicación de la carpeta OneDrive** y espacio en disco local.
- Permisos de **Acceso completo al disco** si el cliente de sincronización lo solicita tras actualización del SO.

## SharePoint y Teams (archivos)
- **Enlace caducado o sin permiso**: regenerar enlace con permisos correctos (solo organización vs externos según política).
- **Coautoría bloqueada**: otro usuario con bloqueo de sección en Office; o archivo marcado como final.

## Rutas largas y caracteres
- Windows puede fallar con rutas muy largas; acortar nombres de carpetas o usar acceso web.
- Evitar caracteres raros en nombres de archivo si la integración con sistemas legacy falla.

## Datos para el ticket
¿Sincroniza o solo falla en web?, tamaño aproximado de biblioteca, mensaje exacto del cliente OneDrive, y si el fallo es en un solo archivo o en toda la biblioteca.
