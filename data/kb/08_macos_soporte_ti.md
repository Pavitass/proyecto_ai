# Soporte TI en macOS (Ventura, Sonoma, Sequoia y posteriores)

## Identificación rápida
- **Versión de macOS**: menú Apple → **Acerca de este Mac** o **Ajustes del Sistema → General → Información**.
- **Chip**: Apple Silicon (M1/M2/M3…) o Intel; afecta a Rosetta y a algunos drivers VPN.

## Cuenta, contraseña y FileVault
- **Olvido de contraseña local**: usar Apple ID de recuperación si está vinculado, o flujo corporativo de MDM/Jamf; no “forzar” sin procedimiento aprobado.
- **FileVault activo**: el disco está cifrado; migraciones y recuperaciones requieren contraseña o clave de recuperación guardada según política.

## Red y VPN en Mac
- **Wi‑Fi conectado sin datos**: olvidar red; renovar DHCP (desactivar/activar Wi‑Fi); revisar **DNS** en detalles del servicio de red.
- **Proxy y PAC**: Ajustes del Sistema → Red → Detalles → **Proxy**; en entornos corporativos suele haber script PAC o proxy explícito.
- **VPN**: comprobar permisos de **Extensiones de red** y **Acceso completo al disco** si el cliente lo solicita; reiniciar el servicio de la app VPN.

## Pantallas y monitores: duplicar (espejo), extender y fallos habituales

### Dónde se configura
- **Ajustes del Sistema → Pantallas** (o **Monitores** según versión). Ahí aparecen los displays detectados (pantalla del Mac, monitor por cable, **Sidecar** con iPad si aplica).
- **Duplicar (espejo)**: activar **Duplicación de pantalla** o **Espejo** para que dos pantallas muestren lo mismo (presentaciones).
- **Extender (escritorio ampliado)**: desactivar duplicación; cada pantalla puede tener resolución y fondo distintos; el cursor se mueve de una a otra según la **disposición** en la vista de iconos de monitores.

### Si no aparece el monitor externo
1. Cable y adaptador (USB‑C/Thunderbolt/HDMI): probar otro puerto del Mac o del hub; cables pasivos largos a veces fallan a 4K.
2. Apagar y encender el monitor; con el Mac encendido, **desconectar y reconectar** el cable.
3. **Detectar pantallas** (menú **Ventana** en algunas apps de sistema, o botón en Ajustes de Pantallas según versión); reinicio con el monitor ya enchufado.
4. Mac con chip Apple: hubs baratos pueden ser inestables; probar conexión directa al Mac para descartar el dock.

### Orden y resolución al extender
- Arrastrar los rectángulos de pantalla para que **izquierda/derecha/arriba** coincidan con el escritorio físico (si el ratón “salta mal”, casi siempre es el orden en la vista).
- **Pantalla principal**: barra blanca en el icono del monitor que tendrá la **barra de menús y Stage Manager**; arrastrar la barra al otro icono para cambiar el monitor principal.
- **Texto borroso o zoom raro**: **Resolución escalada** vs nativa; en pantallas HiDPI, probar “Más espacio” / “Más grande” según necesidad y legibilidad.

### Modo tapa cerrada (solo monitor externo)
Con el Mac **enchufado a corriente** y normalmente con teclado y ratón externos conectados (Bluetooth o USB), cerrar la tapa puede seguir mostrando imagen en el monitor. Si se duerme al cerrar: revisar energía y que el adaptador tenga potencia suficiente; algunos docks exigen driver o firmware.

### AirPlay a TV o a otro Mac como pantalla
Puede servir como segunda pantalla; la latencia y calidad dependen de la red Wi‑Fi. Para trabajo fino con texto, preferir cable.

## Correo y calendario
- **Mail de Apple con Exchange**: borrar cuenta y volver a añadir con autodiscover; revisar que el servidor y el UPN coincidan con lo corporativo.
- **Outlook para Mac**: actualizar desde Microsoft AutoUpdate; problemas de caché a veces mejoran cerrando sesión de la cuenta Office y volviendo a entrar (con backup de datos locales si hay PST/OLM — en Mac lo habitual es cuenta en la nube).

## Permisos de privacidad (muy frecuente en incidencias)
- Micrófono, cámara, grabación de pantalla, accesibilidad: **Ajustes del Sistema → Privacidad y seguridad**; la app (Teams, Zoom, navegador) debe aparecer con interruptor activado.
- Si una app “no ve la cámara” tras actualización del SO: quitar y volver a conceder permiso, o reiniciar.

## Almacenamiento
- **Espacio bajo**: Apple menu → Ajustes del Sistema → General → **Almacenamiento**; vaciar papelera, optimizar almacenamiento, revisar **Descargas** y caché de iCloud Drive.
- **iCloud** “optimizar Mac”: archivos pueden estar solo en la nube; avisar al usuario antes de trabajar offline largo.

## Terminal y diagnóstico ligero (mesa de ayuda)
- `ping` y `traceroute` desde Terminal para conectividad (si la política lo permite).
- **Consola** (app Consola) para filtrar errores de una app concreta en la hora del fallo.

## Impresoras en macOS
- Añadir impresora: Ajustes del Sistema → Impresoras y escáneres; preferir driver **AirPrint** si la impresora lo soporta.
- Cola atascada: botón derecho en la cola → **Restablecer sistema de impresión** (borra colas locales; confirmar con el usuario).

## Datos para el ticket
Versión exacta de macOS, modelo de Mac, si el fallo es solo en Wi‑Fi o también por cable (adaptador USB‑C), y si usa perfil MDM (gestionado por la empresa). Para pantallas: si busca **espejo** o **extendido**, marca de monitor/cable/hub, y si el Mac detecta el display en Ajustes → Pantallas.
