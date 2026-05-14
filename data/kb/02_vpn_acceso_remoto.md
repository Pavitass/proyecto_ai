# VPN y acceso remoto — guía de primer nivel

## Síntomas frecuentes
- "No se puede establecer la conexión" justo después de introducir credenciales.
- El cliente VPN se queda en "conectando…" más de 2 minutos.
- Tras conectar, no hay acceso a recursos internos (intranet, carpetas).

## Comprobaciones iniciales (usuario)
1. Comprobar conectividad general abriendo un sitio público en el navegador.
2. Reiniciar el cliente VPN y volver a intentar.
3. Verificar fecha y hora del equipo (certificados fallan si el reloj está muy desajustado).
4. Si la organización usa MFA, confirmar que el código o la app de segundo factor está sincronizada.

## Windows — restablecer pila de red (sin permisos admin avanzados)
1. Desconectar VPN.
2. Abrir "Solucionar problemas" de red desde el menú Inicio y ejecutar el asistente de red.
3. En "Adaptadores de red", deshabilitar y volver a habilitar el adaptador Wi-Fi o Ethernet.
4. Volver a conectar VPN.

## Errores comunes
- **Credenciales incorrectas**: bloqueo tras varios intentos. Esperar 15 minutos o usar el portal de autoservicio de contraseñas si existe.
- **Certificado no válido**: no aceptar excepciones no solicitadas por TI. Abrir ticket con captura del error.
- **Split tunneling**: si la política corporativa envía solo tráfico interno por VPN, es normal que algunas páginas públicas no pasen por el túnel.

## Cuándo escalar
Si tras dos reinicios del cliente y comprobación de hora/MFA sigue fallando, recopilar logs del cliente VPN (menú diagnóstico si está disponible) y escalar con el ID de error exacto.
