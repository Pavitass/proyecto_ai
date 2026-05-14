# Seguridad: phishing, credenciales y buenas prácticas en mesa de ayuda

## Qué es phishing (recordatorio operativo)
Correo o mensaje que suplica urgencia, imita a IT o al banco, y pide **contraseña**, **código MFA** o **instalar software** desde enlaces extraños. El canal legítimo de TI **no** debe pedir la contraseña por chat informal.

## Respuesta estándar ante correo sospechoso
1. No hacer clic en enlaces ni abrir adjuntos.
2. Reenviar a **phishing@…** o buzón que defina la empresa, o abrir ticket categorizado **seguridad**.
3. Si ya hizo clic: cambiar contraseña por canal oficial, revocar sesiones si la consola lo permite, y notificar a seguridad.

## MFA y fatiga de aprobación
- Rechazar solicitudes de inicio de sesión **no iniciadas** por el usuario.
- No compartir códigos por teléfono con “compañeros” que llaman con prisa.

## Contraseñas y bloqueos
- **Bloqueo por intentos**: esperar ventana de desbloqueo o usar self‑service aprobado; no incrementar intentos al azar.
- **Contraseña en post‑it**: recordar política de empresa; preferir gestor de contraseñas aprobado.

## Equipo perdido o robado
- Reportar de inmediato a TI y seguridad para **revocación de sesión**, **bloqueo remoto** o borrado según MDM.
- No guardar secretos de producción en el escritorio sin cifrar.

## Datos en tickets de seguridad
Hora aproximada, remitente aparente, asunto del correo, y si hubo clic o introducción de credenciales. No pegar contraseñas reales en el ticket.
