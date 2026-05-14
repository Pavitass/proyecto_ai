# Políticas de mesa de ayuda y gestión de tickets

## Objetivo
Estandarizar cómo los usuarios reportan incidencias y cómo el equipo de TI prioriza y resuelve.

## Prioridades
- **critica**: caída de servicio que afecta a muchos usuarios o impide trabajo legal/regulatorio.
- **alta**: el usuario no puede trabajar (sin correo, sin VPN con trabajo remoto obligatorio, PC no arranca).
- **media**: degradación o bloqueo parcial (aplicación lenta, un dispositivo sin red).
- **baja**: peticiones de mejora, dudas de uso, hardware no crítico.

## Datos mínimos en un ticket
1. Qué intentaba hacer el usuario.
2. Mensaje de error exacto o código (copiar/pegar).
3. Si ocurre en un solo equipo o en varios.
4. Sistema operativo y, si aplica, versión de la aplicación.

## Categorías habituales
- **vpn**: acceso remoto, túnel, token, MFA.
- **correo**: Outlook, webmail, buzones compartidos.
- **red**: Wi-Fi, cable, DNS, proxy.
- **impresoras**: colas, drivers, atascos.
- **cuentas**: bloqueos, reset de contraseña (siempre vía canal oficial).
- **otro**: cuando no encaja claramente.

## Escalado
Escalar a un especialista si: se requieren permisos de administrador en servidores, hay indicios de incidente de seguridad, o la base de conocimiento no cubre el caso tras intentar los pasos estándar.

## Cierre y memoria operativa
Un ticket puede pasar a **resuelto** (o **cerrado**) con una **lección** breve guardada en base de datos. Esa lección alimenta las búsquedas de **casos resueltos previos** para incidentes futuros parecidos. La lección debe ser anónima y factual (ver documento en KB sobre memoria de casos resueltos).

## SLA orientativo (demo)
Responder primer contacto en **4 h laborables** para prioridad alta o superior; el resto en **1 día laborable**.
