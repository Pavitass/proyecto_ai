# Navegadores y aplicaciones web (Chrome, Edge, Safari)

## Caché, cookies y sesión
- **Web interna no carga o queda en blanco tras cambio**: borrar **caché e imágenes** del sitio afectado o del dominio corporativo; probar ventana de incógnito para distinguir problema de extensión.
- **Bucle de login SSO**: borrar cookies del dominio de identidad (IdP) y del SaaS; cerrar todas las pestañas del SSO y volver a entrar.
- **“Sitio no seguro”**: comprobar fecha/hora del equipo; certificados interceptados por proxy corporativo (normal en algunas redes con aviso interno).

## Extensiones
- Deshabilitar extensiones recientes si el navegador crashea o la CPU está alta.
- Extensiones de **grabación de pantalla** o **VPN** pueden interferir con aplicaciones web sensibles.

## Políticas corporativas
- **Edge** en Windows suele estar alineado con directivas de grupo; **Chrome** puede gestionarse por política similar.
- **Safari** en Mac: borrar datos de sitios web desde Ajustes del Sistema → Safari → Avanzado / Privacidad según versión.

## PDF y descargas en el navegador
- Si el PDF “no abre”: probar descargar y abrir con visor local; comprobar bloqueo de **ventanas emergentes** o **descargas** por política.

## Datos para el ticket
Navegador y versión, modo incógnito sí/no, mensaje de error exacto, URL (sin datos personales en claro si la política lo prohíbe).
