# 14 · Agentes por tarea, activados desde Lumen

Esta ampliación añade tres identidades OAuth y sus techos OBO. El modo inicial
sigue siendo **Modo actual**, con `chatbot-oidc`. No se cambian los clientes
existentes, las políticas de los usuarios, los proveedores de modelos ni sus
federaciones SPIFFE.

## Uso desde la interfaz

1. Pulsar **Agentes por tarea**, debajo del selector de proveedor, para abrir el
   panel lateral de permisos.
2. Elegir **Consulta**, **Creación de solicitudes** o **Revelado de datos**.
3. Pulsar **Activar y entrar con Verify** y completar el login.
4. Ejecutar la operación y consultar su traza. `verify.client_credentials` y
   `verify.token_exchange` identifican el agente utilizado.
5. Para volver, seleccionar **Modo actual** y entrar de nuevo.

El selector y sus mensajes están disponibles en español e inglés. La elección
está ligada a la sesión autenticada y se conserva al navegar entre conversación
y solicitudes. No se elige un agente más potente automáticamente según la ruta.

### Matriz visual de permisos

El botón **Agentes por tarea** abre a la derecha una matriz de usuarios y agentes.
Empieza cerrado y abrirlo no añade un bloque encima de la conversación. En
escritorio ancho (más de 1700 px) comparte espacio con el chat. En tablet y móvil
se superpone; hasta 760 px ocupa el ancho disponible. El panel tiene desplazamiento
propio y un botón de cierre siempre visible. Se puede cerrar con Escape desde el
panel y el foco vuelve al botón que lo abrió. El borrador del chat se conserva.

Resalta el perfil del usuario autenticado, la columna del agente activo y la celda
**Tu sesión**. El resumen superior muestra sus operaciones esperadas; también
permanece en el botón de apertura cuando se cierra el panel.

| Usuario | Estándar | Consulta | Creación | Revelado |
|---|---|---|---|---|
| Reader | Consultar | Consultar | Consultar | Consultar |
| Writer | Consultar y crear | Consultar | Consultar y crear | Consultar |
| Supervisor | Consultar y revelar | Consultar | Consultar | Consultar y revelar |

Pulsa cualquier celda para comparar: el detalle muestra, para consultar, crear y
revelar, si lo permite el usuario, el agente o ambos. Por ejemplo, Reader + Revelado
indica que el usuario limita el revelado; Supervisor + Consulta indica que lo limita
el agente. Al pulsar una celda, el desplegable **Identidad del agente** selecciona
el agente de esa columna. La fila elegida sigue siendo una comparación: no cambia
el usuario autenticado. **Vista previa** no cambia la identidad activa, la sesión
ni los permisos. **Volver a mi combinación** restaura tanto la celda como el
desplegable al agente activo. Elegir otra opción del selector también actualiza
la vista previa para tu perfil; para activarla sigue siendo necesario pulsar
**Activar y entrar con Verify**.

El perfil activo se deriva de los grupos autenticados, no del nombre del usuario.
Si los grupos combinan escritura y revelado, se añade una fila **Perfil combinado**;
un grupo desconocido se muestra sin acceso. Sin sesión no se marca ninguna celda
como activa. La tabla puede desplazarse horizontalmente en pantallas pequeñas y
sus celdas se pueden activar con el teclado. Está disponible en ES/EN.

La matriz es explicativa según los perfiles de la demo: no lee en directo las
políticas de Vault ni ejecuta operaciones. Verify autentica y emite el token OBO;
**Vault** evalúa usuario ∩ techo del agente ∩ RAR de cada petición. Los bloqueos u
otros cambios en Vault pueden restringir más. **Comprobar límites en Vault** sigue
siendo la comprobación de las llamadas reales. Consultar incluye catálogo,
inventario y solicitudes enmascaradas; revelar recupera los datos protegidos.

[Panel en escritorio](../../chatbot/docs/screenshots/permission-drawer-desktop.png)
· [Tablet](../../chatbot/docs/screenshots/permission-drawer-tablet.png)
· [Móvil](../../chatbot/docs/screenshots/permission-drawer-mobile.png)
· [Comprobación del panel responsive](../../chatbot/docs/permission-drawer-verification.json).
Las capturas del panel se tomaron sin sesión; comprueban la disposición y la
selección, no los permisos efectivos de Vault.

Evidencia anterior al cambio de disposición:
[Reader + Revelado](../../chatbot/docs/screenshots/permission-matrix.png)
· [Comprobaciones de la interfaz](../../chatbot/docs/permission-matrix-verification.json).
[Tabla y desplegable sincronizados](../../chatbot/docs/screenshots/permission-matrix-selector.png)
· [Verificación de la selección](../../chatbot/docs/permission-matrix-selector-verification.json).

**Cambio visible al activar la ampliación:** cambiar de agente comienza una
sesión nueva. Se pierde la conversación y el borrador sin guardar de esa sesión;
las solicitudes ya guardadas permanecen. El selector avisa antes del cambio y
rechaza cambiar durante una operación. El login nuevo es necesario porque cada
token humano autoriza únicamente a su cliente mediante `may_act.client_id`.

## Límites

| Modo | Identidad en Vault | Techo OBO |
|---|---|---|
| Actual | `chatbot-oidc` | El comportamiento previo: permisos del usuario y RAR |
| Consulta | `chatbot-task-read` | Credenciales MySQL RO |
| Creación de solicitudes | `chatbot-task-write` | MySQL RO/RW, Transit encrypt y Transform encode |
| Revelado de datos | `chatbot-task-reveal` | MySQL RO, Transit decrypt y Transform decode |

Siempre se intersectan **permisos del usuario, techo del agente y RAR exacto**.
Por ejemplo:

- Un escritor con Consulta puede consultar, pero Vault deniega credenciales RW,
  cifrado, tokenización, descifrado y destokenización.
- Un lector con Creación sigue sin poder escribir: el agente no amplía su perfil.
- Un supervisor con Consulta no puede revelar; con Revelado sí puede, conforme a
  las políticas existentes.
- Las tres identidades conservan los bloqueos globales del [capítulo 12](12-bloqueos.md).

Consulta puede leer catálogo, inventario y bandeja enmascarada. Su límite se
aplica al rol SQL RO existente, no a tablas individuales. La bandeja sigue siendo
compartida. Esta ampliación no introduce aislamiento por fila ni aprobaciones.

Los proveedores OpenAI, xAI y Claude y la búsqueda Tavily mantienen sus identidades
actuales. Los agentes por tarea controlan las operaciones OBO de negocio; no son
tres ejecuciones paralelas del modelo.

## Instalación y repetición

`./demo.sh start`, el recorrido guiado y el notebook de Lumen incluyen la
preparación de estas identidades. Para añadirlas a una instalación existente,
desde la raíz del repositorio:

```bash
bash -c 'source scripts/demo/common.sh; load_inputs; bash chatbot/scripts/configure-task-agents.sh'
```

El script comprueba primero STS, perfil OAuth y grupos; crea o reconcilia:

- Las apps Verify `vault-chatbot-task-read`, `vault-chatbot-task-write` y
  `vault-chatbot-task-reveal`, con Authorization Code, PKCE S256 y Client
  Credentials. No habilita ROPC ni refresh tokens.
- Sus asignaciones a los tres grupos del laboratorio.
- Tres políticas, entidades sin permisos autónomos, aliases y registros de
  agentes con RAR obligatorio y sin techo `default`.
- `verify/secrets/chatbot/task-agents`, publicado solo cuando están completos los
  tres perfiles, y su lectura en `chatbot-bootstrap`.

Después se carga el código y la configuración en Lumen. Esto reinicia el proceso
y requiere un nuevo login:

```bash
bash scripts/demo/start.sh
```

Una instalación sin el catálogo opcional sigue usando el modo actual; la
interfaz indica que la ampliación no está preparada. No se usa el agente original
como alternativa silenciosa cuando falla un agente por tarea.

La retirada general incluye también las tres apps nuevas en su inventario.
Consultar siempre `./demo.sh remove --dry-run` antes de eliminar recursos.

## Verificación real

```bash
bash chatbot/scripts/verify-task-agents.sh
```

Usa Authorization Code + PKCE con los usuarios ficticios ya instalados; no
modifica sus contraseñas ni evita desafíos de autenticación. Comprueba los cuatro
modos con los tres perfiles de usuario:

- Nueve decisiones reales por combinación en Vault, incluidas denegaciones con
  un RAR que sí describe la ruta solicitada.
- Consulta real del catálogo MySQL.
- Rechazo por Verify si se intenta intercambiar el token humano con otro actor.
- Revocación de los leases de base de datos emitidos por cada caso.

El [informe](../../chatbot/docs/task-agents-verification.json) no contiene tokens
ni contraseñas. Los artefactos de login permanecen en el directorio privado de
estado. Las pruebas de unidad verifican también que el callback usa el audience
y `may_act` del cliente elegido y que el modo original funciona sin la extensión.

## Resto de ampliaciones

| Punto | Estado |
|---|---|
| 1. Agentes separados por tarea | Implementado como opción de interfaz |
| 2. Restricciones RAR por parámetros | [Laboratorio opcional con seis escenarios, comparación real y trazas](15-parametros-rar.md) |
| 3. Espacios de secretos por usuario | [Laboratorio opcional KV v2, aislamiento por entidad humana y trazas](16-espacios-personales.md) |
| 4. Aprobación de operaciones sensibles | Pendiente |
| 5. Bloqueo y revocación por agente | Pendiente; se conservan los bloqueos globales |
| 6. Comparador visual de autorizaciones | Matriz interactiva de permisos esperados disponible; el botón de comprobar límites prueba el agente activo. Comparación en vivo de todas las combinaciones pendiente |

Referencias: [Agent Registry](https://developer.hashicorp.com/vault/ai/iam/concepts/agent-registry),
[OBO](https://developer.hashicorp.com/vault/ai/iam/setup-obo) y
[delegación en Verify](https://docs.verify.ibm.com/verify/docs/oauth-20-token-exchange).

## Identificar al agente y pivotar a Vault

**Comprobar límites en Vault** muestra ahora el agente OBO ligado a la sesión,
además de las nueve decisiones reales. La ficha consulta Vault en ese momento:
registro e ID, descripción, propietario, fechas, estado de la entidad, obligación
de RAR, techo `default`, políticas del techo OBO y políticas directas de la
entidad. Incluye el ID y fechas de la entidad, sus grupos y los alias con su
accessor, issuer y perfil OAuth. Las políticas heredadas de grupos, si existen,
se consultan en Vault; la ficha no calcula permisos efectivos a partir del HCL.

Los enlaces abren **Agent Registry**, la **entidad**, cada **alias** y cada
**política ACL** en el namespace `verify`. En Vault 2.1.2 el panel del agente es
un diálogo sin URL propia: el enlace al registro abre la tabla, donde se busca
el nombre mostrado en Lumen. Entidades, alias y políticas sí tienen URL directa.
Vault utiliza la sesión propia de tu navegador; los enlaces nunca llevan tokens.

En la ventana de la traza, cada llamada muestra **Agente en Vault** y permite
desplegar **Agente, políticas, entidad y alias**. Las políticas incluyen su HCL.
La ficha lleva la hora de consulta: es la configuración actual al abrir la
traza, no una fotografía de las políticas vigentes cuando ocurrió una traza antigua.
Una consulta fallida de metadatos se señala expresamente y no reemplaza ni altera
las decisiones HTTP de las pruebas OBO.

La identidad depende de la llamada:

- OBO y operaciones de negocio: `chatbot-oidc` o el `chatbot-task-*` elegido.
- Credenciales y llamadas al modelo: `chatbot-openai`, `chatbot-anthropic` o `chatbot-xai`.
- Búsqueda Tavily: `chatbot-research`.
- MySQL: se muestra el agente que obtuvo la credencial dinámica. MySQL recibe
  usuario y contraseña, no la entidad de Vault.
- JWKS público: no se atribuye un agente autenticado a la lectura de claves públicas.

### Credencial de inspección

`chatbot/scripts/run.sh` instala `chatbot-agent-inspector` desde
`chatbot/policies/agent-inspector.hcl` y obtiene un token periódico de una hora,
independiente del bootstrap y de los clientes OAuth. Lumen lo renueva cada veinte
minutos y lo revoca al cerrar normalmente. Sólo permite leer las ocho entidades
y registros de Lumen por nombre, las políticas enumeradas y el perfil OAuth
`verify` (esa lectura exige `read` + `sudo` en su ruta exacta). No permite listar entidades, leer secretos, emitir credenciales SQL ni
modificar agentes o políticas. El token queda en el servidor y no entra en la
captura sensible, en el diagrama ni en sus enlaces.

El arranque gestionado copia la política junto al runtime. Se aplica con el
arranque habitual de Lumen; no exige recrear usuarios, agentes ni el cluster.
`LUMEN_VAULT_UI_URL` permite indicar la dirección de Vault accesible desde el
navegador (por defecto `https://127.0.0.1:8443`, sin `/ui`). No cambia la dirección
usada por las llamadas API. La sesión de Lumen se pierde al reiniciar la aplicación.
