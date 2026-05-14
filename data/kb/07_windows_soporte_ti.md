# Soporte TI en Windows (10 y 11)

## Identificación rápida
- **Versión**: Configuración → Sistema → Acerca de (o `winver` en Ejecutar).
- **Arquitectura**: 64 bits es lo habitual en equipos corporativos.

## Arranque y sesión
- **Pantalla negra o congelada en inicio**: forzar apagado manteniendo el botón de encendido; al arrancar, si aparece **Reparación automática**, dejar que termine una vez. Si entra en bucle, escalar (imagen/recuperación).
- **No acepta contraseña tras cambio de dominio/MFA**: comprobar teclado (mayúsculas, idioma), cable de red si hay política de bloqueo offline, y canal oficial de reset (nunca por teléfono no verificado).
- **Perfil temporal** (“estás conectado con un perfil temporal”): no guardar trabajo local; reinicio; si persiste, TI debe revisar registro/perfil en `C:\Users`.

## Red y VPN en Windows
- **Wi‑Fi conectado “sin Internet”**: olvidar red y volver a conectar; `ipconfig /release` y `ipconfig /renew` en CMD como administrador si procede; comprobar proxy en **Configuración → Red e Internet → Proxy**.
- **DNS**: en adaptador, IPv4 puede usar DNS corporativos o automáticos según política; no mezclar VPN con DNS públicos si la empresa lo prohíbe.
- **Adaptador deshabilitado**: Panel de control → Centro de redes → Cambiar configuración del adaptador → clic derecho Habilitar.

## Pantallas y monitores: duplicar, extender y fallos habituales

### Cómo cambiar el modo (lo primero que debe probar el usuario)
- **Atajo de teclado**: **Windows + P** abre el conmutador rápido. Opciones típicas:
  - **Solo pantalla de PC**: solo el monitor del portátil (o el principal en torre).
  - **Duplicar**: la misma imagen en todos los monitores (presentaciones, aulas).
  - **Extender**: escritorio amplio; el ratón “viaja” de un monitor a otro (trabajo diario con segundo monitor).
  - **Segunda pantalla solamente**: apaga el panel del portátil y usa solo el externo (dock con tapa cerrada si la política de energía lo permite).
- **Desde ajustes**: **Configuración → Sistema → Pantalla** (o **Pantallas** en Windows 11). En **Varias pantallas** elegir **Duplicar** / **Extender** / **Mostrar solo en 1 o 2**.

### Si no detecta el segundo monitor
1. Comprobar cable y puerto (probar otro puerto USB‑C/HDMI/DisplayPort del equipo o del dock).
2. **Detectar**: en Configuración → Pantalla → **Detectar** (o **Identificar** para ver números en cada pantalla).
3. Desenchufar y volver a enchufar el dock **con el portátil ya encendido**; si no, reinicio con el monitor ya conectado.
4. **Actualizar o revertir driver de gráficos** (Intel / NVIDIA / AMD) solo vía canal corporativo o Windows Update; evitar drivers aleatorios de la web.

### Problemas comunes tras extender
- **Resolución o texto borroso**: en cada pantalla, **Escala** (100 %, 125 %, 150 %); alinear porcentajes similares entre monitores si molesta el salto de tamaño del cursor.
- **Monitor “a la izquierda” pero el ratón va al revés**: Pantalla → **Reordenar** los rectángulos para que coincidan con la mesa física.
- **Presentación en la pantalla equivocada**: marcar **Pantalla principal** en la pantalla deseada; en PowerPoint, modo presentador permite elegir monitor de diapositivas.
- **Parpadeos o apagones**: cable defectuoso, dock sin alimentación suficiente, o frecuencia de actualización (Hz) incompatible; bajar temporalmente resolución o Hz en Propiedades del adaptador de pantalla.

### Tapa del portátil cerrada con monitor externo
Depende de la política de energía: **Configuración → Sistema → Energía y batería** (o **Opciones de energía** en Panel de control) → comportamiento al cerrar la tapa: **No hacer nada** cuando está **Enchufado** (solo si la empresa lo permite y hay refrigeración adecuada).

## Correo y Office (orientación mesa de ayuda)
- **Outlook no abre o se cierra**: Inicio en modo seguro (`outlook.exe /safe`), deshabilitar complementos recientes, reparar Office desde **Aplicaciones y características → Modificar → Reparación rápida**.
- **Buzón compartido no visible**: Archivo → Configuración de cuenta → Configuración de cuenta de Exchange → Más configuraciones → Avanzado → buzones adicionales (según versión).
- **Archivos bloqueados “en uso”**: cerrar vista previa del Explorador, reiniciar el proceso `explorer.exe` solo si el usuario está informado.

## Impresoras en Windows
- Cola atascada: **Servicios** → Detener **Cola de impresión**, vaciar `C:\Windows\System32\spool\PRINTERS` (solo con guía TI si no hay permisos), iniciar servicio.
- Driver incorrecto: eliminar dispositivo y volver a agregar con paquete del fabricante o catálogo corporativo.

## Rendimiento y disco
- **Disco lleno**: Liberador de espacio, vaciar papelera, revisar carpetas de descargas y `Downloads` de Teams; OneDrive “Liberar espacio” si está en uso.
- **Lentitud general**: Administrador de tareas → Inicio (deshabilitar apps innecesarias), revisar uso de disco al 100 % (a veces indexación o antivirus).

## Seguridad básica en el puesto Windows
- BitLocker: si el equipo lo exige, no desactivar sin autorización; guardar clave de recuperación según política.
- Actualizaciones: **Windows Update** y reinicios en ventana permitida; posponer solo dentro de lo que permita la empresa.

## Datos para el ticket
Incluir edición de Windows (Home/Pro), si es portátil o torre, si ocurre conectado a VPN o solo en oficina, y capturas de mensajes de error exactos. Para pantallas: modo deseado (duplicar / extender), tipo de cable o dock, y si **Win+P** cambia el comportamiento.
