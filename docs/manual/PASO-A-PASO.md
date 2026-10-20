# Ejecutar Lumen un paso cada vez

Desde la raíz del repositorio, con `.env` preparado según [00 · Entorno](00-entorno.md):

```bash
bash scripts/manual/paso-a-paso.sh
```

Funciona desde zsh o Bash 3.2. No hay que cargar `session.sh` ni pegar bucles, JSON o comandos multilínea. Cada paso abre un proceso Bash, carga `.env` y la conexión guardada de Vault, y ejecuta un archivo del repositorio.

El menú muestra el alcance, el script y el capítulo correspondiente **antes de ejecutar**:

- **Enter:** ejecutar solamente el paso mostrado.
- **v:** ver su código.
- **l:** consultar todos los pasos y su historial.
- **Número o ID:** seleccionar otro paso; después Enter lo ejecuta.
- **q:** salir. Al volver a abrir el script, se retoma el recorrido.

Si falla un paso, se conserva como pendiente de resolver y no se ejecuta el siguiente. El error no cierra tu shell. Cada intento tiene un log privado distinto; el menú muestra su ruta. No hay reintentos automáticos de escrituras.

Antes de cada ejecución se comprueba la sintaxis de `.env` y del archivo Bash elegido. Una comilla sin cerrar se detecta antes de cargar las variables o ejecutar comandos de ese archivo. Si interrumpes un paso con **Ctrl+C**, se detiene su proceso y queda pendiente para retomarlo.

## Retomar la instalación que quedó a medias en Verify

Si Vault, MySQL y las entradas en `verify/secrets` ya están preparados:

```bash
bash scripts/manual/paso-a-paso.sh desde verify-base
```

El recorrido pasa por **RAR → OIDC → research → STS → usuarios y grupos → Database y protección → agentes Vault**, y continúa con los tres proveedores, observabilidad, arranque y pruebas. Los pasos anteriores al punto seleccionado quedan sin marcar: no se supone que ya hayan sido comprobados.

También puedes ejecutar exactamente una operación y volver al prompt:

```bash
bash scripts/manual/paso-a-paso.sh ejecutar research
```

```bash
bash scripts/manual/paso-a-paso.sh siguiente
```

`siguiente` ejecuta **un solo paso**, no todo el resto. `ejecutar ID` vuelve a ejecutar el paso indicado aunque ya figure como completado.

```bash
bash scripts/manual/paso-a-paso.sh lista
```

```bash
bash scripts/manual/paso-a-paso.sh ver agentes
```

## Reanudación y recursos existentes

Los pasos de Verify obtienen un token administrativo nuevo en cada ejecución. Las aplicaciones se buscan por nombre antes de crear; los nombres ambiguos detienen el paso. Si hay varios `vault-chatbot-sts`, se utiliza el `client_id` guardado en `verify/secrets/chatbot/sts` únicamente cuando coincide con uno de ellos en el inventario actual. No se borra ningún duplicado ni se elige el primero arbitrariamente.

Los usuarios se buscan antes del POST. Una cuenta existente conserva su contraseña si no está pendiente de activación; se completa su `user_id` en Vault y se añade al grupo solo cuando falta. Una credencial ausente o incompatible detiene el paso antes de modificar usuarios. El registro de agentes comprueba primero que existen las credenciales de `oidc` y `research`.

El paso `grupos` comprueba los tres grupos, sus usuarios y las políticas antes de empezar a modificar entidades o permisos. El capítulo [04](04-vault-iam.md) llama a este mismo archivo y carga el entorno aunque se ejecute desde una terminal nueva.

Los pasos de infraestructura reutilizan los recursos existentes según sus scripts. Configurar de nuevo puede actualizar políticas, parámetros, datos de demostración y servicios: el alcance se muestra en cada paso. Este recorrido no llama a `remove`, `rebuild` ni `demo.sh start`.

El progreso se guarda en `${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/guided/progress.json`, con logs y reportes en ese mismo directorio privado. Exporta `LUMEN_STATE_DIR` antes de arrancar si usas otro directorio. Los estados `OK` son historial de ejecuciones, no una comprobación continua: después de cambiar el despliegue, ejecuta de nuevo los pasos necesarios.

## Pausas de consola y comprobación real

- **OpenAI:** `openai-recursos` prepara proyecto y cuenta; antes de ejecutar `openai-mapping`, completa WIF según [07](07-openai-spiffe.md) y guarda los IDs en `.env`.
- **Claude:** completa inicialmente emisor, regla, cuenta e inicio de sesión `ant` según [08](08-claude-spiffe.md). `claude-jwks` sincroniza las claves públicas actuales por la API oficial y comprueba el resultado antes de `claude-agente`. Si se recrea Vault, el mismo paso actualiza el emisor existente.

El script vuelve a leer `.env` en cada paso. No marca la federación como probada por el mero hecho de que los IDs estén presentes.

Los pasos finales prueban salud y catálogo, Database/research, los nueve permisos OBO de cada usuario y los intercambios e inferencias de xAI, OpenAI y Claude. Estas pruebas emiten credenciales temporales y consumen uso de los proveedores. `probar-obo` utiliza el flujo Cloud Directory del laboratorio y se detiene ante MFA o formularios no soportados. Las pruebas de bloqueos y revocación del [capítulo 12](12-bloqueos.md) son un recorrido separado.

El paso de aplicación instala también **EN/ES**: no hay un paso adicional de idioma ni variables nuevas. Al abrir Lumen, se aplica la preferencia del navegador o la elección guardada con los botones. Los verificadores de servicios no sustituyen la [comprobación visual bilingüe del capítulo 10](10-aplicacion.md#idioma-y-comprobaciones-bilingües), que revisa la conservación del formulario, el idioma de las respuestas y el visor de trazas.

La validación local de este ejecutable comprueba sintaxis, reanudación y respuestas simuladas de Verify/Vault. La instalación completa queda verificada en tu entorno cuando pasan sus pasos reales de comprobación.
