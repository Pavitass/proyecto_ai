# Memoria operativa: tickets resueltos

## Qué es
Los tickets que pasan a estado **resuelto** (o **cerrado**) pueden llevar una **lección** guardada en base de datos: texto breve que resume qué ocurría y cómo se cerró el caso. Esa información **no es ficticia**: sale de conversaciones y cierres reales registrados en el sistema.

## Cómo lo usa el asistente
- Al abrir un caso nuevo, además de la KB en archivos, el agente puede consultar **casos resueltos anteriores** parecidos (misma herramienta interna que la aplicación expone al modelo).
- Las coincidencias se basan en palabras del síntoma y en categoría, título, descripción y lección ya guardada.
- Si no hay ningún ticket resuelto aún, el flujo sigue solo con KB y el ticket actual.

## Cómo debe cerrarse un caso (política)
- La lección debe ser **anónima**: sin correos personales, nombres propios, teléfonos, contraseñas ni datos que violen privacidad.
- Debe ser **útil para el futuro**: síntoma observable, comprobaciones que importaron, acción que resolvió o que descartó causas.
- No sustituye la KB oficial de políticas; **complementa** con experiencia acumulada del servicio.

## Estados
- **resuelto** o **cerrado**: el caso entra en el conjunto consultable como precedente.
- Otros estados (por ejemplo **en_diagnostico**, **escalado**) no se usan como precedentes de cierre hasta que el caso se marque resuelto con lección cuando corresponda.
