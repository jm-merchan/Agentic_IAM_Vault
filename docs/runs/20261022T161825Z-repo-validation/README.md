# Validación final del repositorio · 22 de octubre de 2026

Revisión posterior a la incorporación de **Cómo decide Vault**. Se comprueban
el código final, las pruebas, los generadores de notebooks, los documentos,
los archivos estructurados, las capturas y la correspondencia con el runtime.

## Ajustes encontrados

- Una respuesta de Loki con JSON válido pero sin un objeto en la raíz producía
  un error interno. Ahora se considera auditoría no disponible. Cuatro pruebas
  de regresión reprodujeron el fallo antes de la corrección.
- Cinco enlaces de informes históricos apuntaban a capítulos renumerados.
  Se actualizaron sus destinos y etiquetas.
- Dos salidas históricas `before.json` estaban vacías. Se conservan los mismos
  cero bytes como `before.empty.txt`, con una aclaración en cada ejecución. No se
  reconstruye ni se inventa el inventario que faltaba.
- Los índices de revisión y validación incorporan este cierre y enlazan la
  verificación visual del desplegable realizada anteriormente.
- El notebook 10 conservaba metadatos locales del kernel distintos de su
  generador. Se regeneró y se comprobó que todas sus celdas siguen idénticas.

## Evidencia

Pasaron **569 pruebas Python y 2 subtests**, **15 pruebas JavaScript** y la
comprobación de dependencias de los **124 paquetes** del entorno. Los diez
notebooks generados coinciden con sus siete generadores. Terraform archivado
pasa formato y validación. El JSON enlazado recoge también los recuentos finales
de documentos, enlaces, archivos y capturas, y los hashes del runtime.

[Resultados finales](verification.json) ·
[JSON, YAML y enlaces de todos los documentos](repository-files.json) ·
[Correspondencia de notebooks y generadores](notebook-generation.json) ·
[Terraform archivado de Okta](terraform-check.json) ·
[Hashes del código publicado](runtime-files.json) ·
[Lectura de auditoría desde el runtime](live-audit-smoke.json)

Los 55 archivos de aplicación y estáticos coinciden con el runtime; Lumen,
Grafana, Loki y Tempo responden con HTTP 200. La versión publicada correlaciona
una petición real ya registrada, y el endpoint rechaza la misma consulta sin
sesión. No se ha generado otra operación de Vault para esta comprobación.

Las [capturas vigentes](../../screenshots/current/manifest.json) conservan su
procedencia y SHA-256. La [verificación visual de Vault](../20261022T154444Z-vault-decision/README.md)
cubre ES/EN, móvil y ambos temas. Las capturas y resultados anteriores mantienen
su fecha; esta revisión no equivale a otra reinstalación, a una nueva aprobación
CIBA ni a confirmar la recepción del PDF por el navegador.

Los generadores se ejecutan en una carpeta temporal y se comparan con los
notebooks del repositorio. Terraform se inicializa de forma aislada, con el
backend desactivado y el archivo de versiones bloqueado: no se ejecutan planes
ni cambios de infraestructura. Los logs completos permanecen en el directorio
privado de esta ejecución.
