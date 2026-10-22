# Capturas de la interfaz actual

Las guías activas y los notebooks usan las imágenes de [current](current).
Son capturas reales del navegador, tomadas durante la
[revisión del 22 de octubre](../runs/20261022T140230Z-workspace-review/README.md).
El [manifiesto](current/manifest.json) identifica página, fecha, descripción y
SHA-256. Los datos de solicitudes son ficticios.

Al cambiar la interfaz, repite el recorrido correspondiente, captura su resultado
visible y actualiza la imagen y su entrada del manifiesto. Comprueba escritorio,
390 px, ES/EN y tema oscuro cuando afecte al componente. Regenera los notebooks
con los scripts `chatbot/scripts/build-*-notebook.sh` aplicables y ejecuta
`python3 scripts/manual/validate.py`.

Los informes fechados conservan las imágenes que acreditaron su ejecución. No
sustituyas esas imágenes por una captura posterior. Las referencias antiguas a
consolas externas se etiquetan como históricas; no acreditan su interfaz actual.
