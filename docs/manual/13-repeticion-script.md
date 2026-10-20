# 13 · Repetir las guías desde cero por script

Para avanzar paso a paso o reanudar una instalación incompleta, utiliza el [recorrido guiado](PASO-A-PASO.md). El ensayo de este capítulo es distinto: su operación `rebuild` retira recursos y reconstruye el laboratorio.

[Índice](README.md) · Requiere [00](00-entorno.md) · [Resultado de la validación](VALIDACION.md)

Este ensayo ejecuta los bloques Bash de los capítulos 00–10, incluyendo siempre xAI, OpenAI y Claude, en su orden de dependencia. Extrae los comandos directamente del Markdown y registra el hash SHA-256 de cada bloque ejecutado. Los bloques que invocan un archivo ejecutan ese archivo del repositorio; el capítulo 04 utiliza comandos independientes para runtime, grupos y bootstrap. No llama a `demo.sh start`. Vault se configura mediante su CLI; las APIs externas se invocan con curl.

## 1. Preparar las entradas

Completar `.env` según 00 y arrancar el motor de contenedores. Para repetir con OpenAI deben estar guardados `OPENAI_PROJECT_ID`, `OPENAI_SERVICE_ACCOUNT_ID` y `OPENAI_IDENTITY_PROVIDER_ID`, además de la Admin API key y ngrok. Para Claude se conservan los cinco IDs WIF de [08](08-claude-spiffe.md) y se prepara el perfil OAuth administrativo `lumen-admin`. La instalación sincroniza las nuevas claves públicas por la API oficial antes del primer intercambio. Los recursos WIF externos se conservan.

Las cuentas de prueba son usuarios Cloud Directory con contraseña activa, sin MFA exigido por una política adicional. El script se detiene si encuentra MFA, cambio de contraseña o un formulario desconocido. No evita esos controles ni utiliza el grant de contraseña ROPC. Perl analiza HTML recibido por curl; no controla un navegador.

## 2. Retirar y reconstruir

Desde la raíz del workspace:

```bash
bash scripts/manual/rehearse.sh rebuild
```

El comando inventaría la retirada con `demo.sh remove --dry-run`, detiene los procesos manuales registrados, ejecuta `demo.sh remove`, comprueba que los tres namespaces han desaparecido e instala desde los bloques de las guías. Los procesos de Lumen y los forwards quedan activos para mostrar después la demo.

En macOS, `caffeinate -ims` inhibe la suspensión por inactividad, del disco y del sistema mientras dura el ensayo; la inhibición de suspensión del sistema requiere alimentación de corriente. El paso 01 comprueba el reloj de la VM y sincroniza Podman si quedó atrasado tras una suspensión anterior. Mantén el equipo abierto y conectado durante la ejecución. Una suspensión forzada o cerrar la tapa puede interrumpir la red y dejar caducar credenciales de cinco minutos; ese ensayo se considera fallido, no se oculta como resultado correcto.

Se eliminan los recursos de Lumen en los namespaces Kubernetes `vault`, `mysql` y `lumen-observability`, sus volúmenes, las apps/STS/usuarios/grupos de Lumen en Verify y el estado operativo retirado por `remove`. Se conservan `.env`, el cliente administrativo y esquema RAR compartido de Verify, el proyecto/cuenta/mapping OpenAI, el perfil Minikube, la caché de imágenes y los recursos ajenos a Lumen. Por tanto, este ensayo reconstruye el laboratorio sobre sus cuentas externas preparadas; no recrea esas cuentas.

Se habilita audit inmediatamente después de inicializar Vault. Las tres ramas se configuran siempre. `LUMEN_MODEL_PROVIDER` solo establece el proveedor inicial del banner; no controla qué ramas se instalan o verifican. Antes de retirar recursos se exige que estén presentes las credenciales y los IDs externos de las tres integraciones. Los pasos condicionales de creación del proyecto/cuenta OpenAI se omiten al reutilizar sus IDs.

`rebuild` e `install` terminan la instalación local, generan `claude-jwks.json` dentro del directorio de ejecución y sincronizan el emisor existente. El resultado se comprueba mediante una lectura posterior de la API. Continuar con las pruebas reales:

```bash
bash scripts/manual/rehearse.sh verify
```

La ruta del informe pendiente se guarda en `$MANUAL/pending-verification-run`. Al ejecutar `verify` en una terminal nueva se reutiliza esa ruta, se finaliza el resultado del ciclo y solo entonces se retira la marca pendiente. Si la validación falla, la marca se conserva para diagnosticar y reintentar. Para verificar un despliegue distinto, indicar explícitamente `MANUAL_RUN` con un directorio nuevo.

La instalación y la verificación funcional se ejecutan como fases separadas. La fase `verify` ejecuta los bloques 8–14 de Claude, precedidos por su bloque de entorno, incluida la inferencia y el replay negativo, antes de los recorridos generales.

## 3. Validar los recorridos por script

Después de la sincronización de claves durante la instalación, `verify` ejecuta estas pruebas:

- Login de lector, gestor y supervisor mediante Authorization Code + PKCE, con cookies independientes, `state`, nonce y validación de firma/issuer/audiencia/caducidad.
- Nueve permisos Vault por perfil, catálogo SQL, solicitud con cinco pasos y datos sintéticos, idempotencia, lectura enmascarada y revelado autorizado.
- Bloqueos Database y decrypt con JWT anteriores y nuevos; retirada del bloqueo y reutilización del JWT todavía válido.
- Deep Agents con catálogo OBO, búsqueda Tavily y rechazo de preguntas ajenas a energía.
- Selección por sesión de OpenAI, xAI y Claude sobre un único catálogo: herramientas de catálogo/Tavily, ámbito, modelo de la traza e identidad SPIFFE correspondiente. xAI comprueba además caché reautorizada, reemplazo antes de caducar, bloqueo y revocación.
- Trazas en Tempo y pares request/response de Vault en Loki correlacionados con cada acción.

Las operaciones funcionales usan los servicios reales de la aplicación Python, sin mocks. El aprovisionamiento y los cambios de políticas siguen usando Bash, curl y Vault CLI. Esta prueba no inspecciona visualmente el CSS ni pulsa botones de NiceGUI; esos recorridos visuales se describen en [10](10-aplicacion.md).

Para repetir solo las verificaciones sobre una instalación manual activa:

```bash
bash scripts/manual/rehearse.sh verify
```

Cada ejecución guarda una solicitud sintética y emite credenciales temporales. Los bloqueos se retiran al acabar sus pruebas, también si falla una aserción dentro de ellas.

## 4. Leer las evidencias y detener los procesos

El comando imprime el directorio `docs/runs/<fecha>-manual-script/`. `installation.json` contiene los bloques y sus hashes; `workflows.json`, las aserciones y los IDs de traza. Un ciclo completo añade `before.json`, `after.json`, el inventario de retirada y `result.json`. Este último solo se crea tras terminar ambas fases y exige namespaces con UID nuevos y todas las comprobaciones correctas.

Los logs detallados, cookies, tokens y contraseñas se guardan en `~/.local/state/lumen-vault-demo/manual/`, con permisos privados. La repetición archiva ese directorio en `manual-archives/` antes de recrearlo; estos archivos privados tampoco deben publicarse. Un fallo detiene la ejecución y deja los logs para diagnóstico: no vuelve a enviar automáticamente POST de creación. El inventario Verify de la retirada permite dos reintentos de GET ante errores transitorios; no repite POST ni DELETE automáticamente. El reloj se comprueba al empezar, antes de configurar cada proveedor de modelos y antes de los workflows.

Para detener únicamente los procesos iniciados por este ensayo y conservar los recursos:

```bash
bash scripts/manual/stop.sh
```

Implementación: [runner](../../scripts/manual/rehearse.sh), [instalación de bloques](../../scripts/manual/install.sh), [login OIDC](../../scripts/manual/oidc-login.sh) y [pruebas funcionales](../../scripts/manual/workflows.py).

## Comprobar las guías sin desplegar

`python3 scripts/manual/validate.py` comprueba los enlaces locales y la sintaxis de todos los bloques Bash y scripts; actualiza `docs/manual/validacion.json`. Las pruebas `cd chatbot && /tmp/vault-chatbot-venv/bin/python -m pytest -q tests/test_manual_configuration.py` ejecutan los bloques de catálogo con un Vault simulado y comprueban la planificación y la reanudación del ensayo. No recrean infraestructura ni emiten credenciales reales. Estos controles no sustituyen el ciclo completo con sus servicios externos.
