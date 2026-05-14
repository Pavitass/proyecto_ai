# Impresoras en entorno de oficina

## La impresora no aparece
1. Comprobar que la impresora esté encendida y en la misma red (o USB firmemente conectado).
2. En Windows: Configuración → Bluetooth y dispositivos → Impresoras; ejecutar solucionador de problemas.
3. Si la impresora es de red, hacer ping a la IP de la impresora (si la política lo permite) o pedir IP al equipo de TI.

## Atasco de papel
1. Seguir las flechas del fabricante para abrir tapas.
2. Tirar del papel con suavidad en la dirección natural de salida; no forzar.
3. Tras limpiar, imprimir página de prueba desde el panel de la impresora si existe.

## Cola de impresión bloqueada
1. Servicios de Windows → detener "Cola de impresión".
2. Borrar contenido de `C:\Windows\System32\spool\PRINTERS` solo si las políticas lo permiten (a veces requiere admin).
3. Reiniciar el servicio "Cola de impresión".

## Mala calidad de impresión
1. Sustituir tóner/cartucho según indicador del dispositivo.
2. Ejecutar utilidad de limpieza de cabezales en inyección de tinta.
3. Actualizar driver desde el sitio del fabricante si la versión actual falla tras actualización de SO.
