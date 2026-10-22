# Revisión integral · 22 de octubre de 2026

Revisión del código, documentación, notebooks, interfaz y servicios sobre la
instalación reconstruida ese mismo día. No se retiró de nuevo el despliegue.
Los JSON conservan resultados, fechas y alcance. Los intentos fallidos se
publican separados de las repeticiones correctas.

## Correcciones encontradas

- Las guías de uso y los generadores de notebooks incluían capturas de interfaces
  anteriores. Se sustituyen por capturas reales en `docs/screenshots/current`,
  con fecha, página y manifiesto. Los informes históricos conservan sus imágenes.
- Varias instrucciones y el prompt del agente usaban «Guardar solicitud» / «Save
  application», aunque la acción actual es «Guardar borrador» / «Save draft».
- «Ver última traza» en Solicitudes conservaba la traza de carga inicial tras
  revelar datos o descargar un PDF. Se actualiza también después de un error.
- Cambiar ES/EN en un enlace de traza con `?span=` perdía la llamada seleccionada.
  El selector conserva ese parámetro, limitado a un Span ID hexadecimal válido;
  pruebas de redirección y navegador comprueban que sigue seleccionado Vault 403.
- El clasificador rechazó una búsqueda de autoconsumo solar y preguntas sobre
  OBO de Lumen. Se aclara
  que una búsqueda pública sobre energía pertenece al ámbito y se utiliza
  temperatura 0 solo para la clasificación OpenAI. Los otros proveedores y las
  llamadas de conversación conservan su configuración.
- El contador global de Grafana superaba el límite de 500 series al agrupar por
  request.id. Ahora cuenta eventos sin crear una serie por ID y lo indica en su
  título y descripción. Varias copias del mismo ID son varios eventos, no varias
  operaciones de negocio. Se actualizan también Claude, CIBA y KV en el panel.
- La guía confundía captura raw del cliente con auditoría raw de todas las rutas.
  Se explicita que KV personal y contratos se auditan con HMAC. El verificador de
  valores raw ahora informa claramente de esa limitación; no se cambian filtros
  ni se rebajan comparaciones.
- El validador revisa enlaces y anclas, Markdown de notebooks y procedencia de
  capturas. Rechaza imágenes históricas incrustadas en guías actuales.

## Evidencias verificadas

| Área | Resultado y evidencia |
|---|---|
| Pruebas locales | [532 pruebas Python, 2 subtests y 12 pruebas JavaScript](local-tests.json), todas correctas |
| Documentación y sintaxis | [Validación estática](static-validation.json): 38 documentos, 701 enlaces, 11 notebooks, 273 bloques Bash, 92 scripts y 90 archivos Python, sin errores |
| Servicios completos | [137 comprobaciones y 54 trazas](workflows.json), todas correctas en el segundo intento |
| Primer intento | [Falso rechazo de búsqueda solar](workflows-first-attempt.json) y [decisión del modelo](guardrail-first-failure.json) |
| Clasificador | [16 casos y 6 comprobaciones SVID](guardrails-verification.json); [primer intento adversarial](guardrails-first-attempt.json) conservado |
| Tres proveedores | [48 casos: dos repeticiones de ocho formulaciones por proveedor](scope-repetitions.json), todos correctos tras aclarar la arquitectura de Lumen; [primer intento, con cuatro rechazos](scope-repetitions-first-attempt.json) conservado |
| Agentes por tarea | [12 combinaciones](task-agents-verification.json): nueve decisiones Vault, catálogo MySQL y rechazo de actor distinto por combinación |
| Espacios personales | [12 combinaciones](personal-spaces-verification.json): acceso propio, CAS, techos y acceso cruzado |
| Parámetros RAR | [Cuatro combinaciones de perfil y agente](rar-parameters-verification.json), con las comparaciones registradas por caso |
| Auditoría de Chrome | [Ocho trazas con valores raw comparados](ui-audit-correlation.json); [tres trazas con correlación de metadatos](ui-protected-audit.json), que incluyen rutas con HMAC |
| Notebooks | [Nueve notebooks de la raíz](notebooks.json): celdas ejecutables intactas y sin salidas; cuatro regenerados para renovar texto e imágenes |
| Runtime | [54 archivos de aplicación y recursos, y dashboard de Grafana](runtime-files.json) cotejados con el código publicado |
| Grafana | [Consultas sin filtro y por Trace ID](dashboard-queries.json), HTTP 200, incluido un total superior a 500 |
| Navegador | [Comprobaciones y Trace ID](ui-checks.json) |
| Imágenes | [45 capturas actuales con fecha y SHA-256](../../screenshots/current/manifest.json), revisadas visualmente; [inventario de referencias actualizado](image-inventory-after.json) |
| Estado final | [Servicios activos y bloqueos adicionales desactivados](final-state.json); siguen aplicando los permisos de cada perfil, el techo del agente y RAR |

La revisión en Chrome incluye ES/EN, tema claro/oscuro, 390 px, permisos de los
perfiles Reader/Writer/Supervisor, catálogo, xAI, Tavily, validación de DNI,
formulario, guardado, bandeja enmascarada, revelado denegado/autorizado,
bloqueo/restauración de descifrado, comparación RAR, espacios personales,
repetición HTTP de JWKS públicos y Grafana. También se probó el cambio efectivo
a Supervisor + Consulta, el aislamiento explicado en ES/EN y móvil, y la
conservación del paso de Vault al cambiar de idioma.

El nuevo borrador de prueba es `f0bd7519-28cc-411f-b583-7ce73cb2b0dd`. Writer lo
guarda y no puede revelarlo; Supervisor recupera los mismos datos ficticios.

## Lectura de las evidencias

Las capturas activas se renuevan juntas en `docs/screenshots/current`; cada una
conserva su momento de captura, no el estado de todas las sesiones a la vez.
Las capturas de formularios y resultados usan exclusivamente datos ficticios.
El código publicado se acredita por hashes: el commit del contexto es la base
de la revisión y los cambios de esta revisión siguen en el árbol de trabajo.

El primer intento de comparar el PDF con auditoría raw falló en la lectura de
`secrets/data/lumen-contracts/...`: esa ruta tiene HMAC. Se conservó el requisito
de igualdad raw y se verificó por separado la correlación de metadatos del PDF.
Los informes distinguen los valores efectivamente comparados de los metadatos.

## Alcance y límites

La aprobación CIBA y la comprobación de integridad del PDF pertenecen al
[ensayo de reinstalación anterior de este mismo día](../20261022T122934Z-full-e2e/README.md).
Aquí se comprobó la persistencia del contrato en otra sesión del Writer y se
volvió a pulsar la descarga. La herramienta no recibió el evento de descarga en
15 segundos: **no se acredita que Chrome haya guardado el archivo**. No se pidió
otra aprobación al Validador.

Las capturas del portal externo OpenAI/Claude que siguen enlazadas en las guías
son referencias históricas explícitas. No se presentan como vistas actuales.
La clasificación del ámbito depende de un modelo; las pruebas son una muestra,
no una garantía universal. Vault mantiene los controles de autorización fuera
del modelo.
