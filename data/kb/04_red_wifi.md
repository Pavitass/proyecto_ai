# Red local, Wi-Fi y conectividad básica

## Sin acceso a Internet
1. Comprobar si solo falla Wi-Fi o también cable.
2. Olvidar red Wi-Fi problemática y volver a conectar con credenciales correctas.
3. Ejecutar `ipconfig /release` y `ipconfig /renew` en símbolo del sistema (Windows) si la política lo permite.
4. Probar DNS públicos solo en diagnóstico si la política lo permite; en muchas empresas el DNS es interno y no debe cambiarse sin autorización.

## "Conectado sin Internet"
1. Abrir portal cautivo del Wi-Fi invitado si es red de visitantes.
2. Desactivar temporalmente VPN para descartar rutas forzadas.
3. Reiniciar el punto de acceso o pedir reinicio remoto al equipo de redes si afecta a varios usuarios.

## Lentitud intermitente
1. Medir velocidad con herramienta aprobada por la empresa.
2. Cerrar aplicaciones que suban mucho ancho de banda (sincronización de nube masiva).
3. Si solo afecta a un sitio interno, puede ser servidor; abrir ticket con hora aproximada y URL.
