# 16 · Espacios de secretos por usuario

**Mi espacio de secretos** añade un laboratorio de KV v2 con OBO y aislamiento
por identidad humana, en el namespace `verify`. Conserva la bandeja compartida,
MySQL, Transit, Transform y las credenciales de los modelos. Estos valores no
se envían al LLM.

## Preparación

Después de `grupos`, con el [runtime Python instalado](10-aplicacion.md#2-instalar-el-runtime),
ejecutar desde la raíz del repositorio:

```bash
bash scripts/manual/paso-a-paso.sh ejecutar espacios-personales
```

Carga `.env` y la conexión privada de Vault. Requiere los tres usuarios, sus
entidades humanas y el agente estándar. Incluye los agentes por tarea que
existan. `./demo.sh start` incorpora el mismo paso. Para cargar únicamente los
cambios de aplicación en una instalación existente:

```bash
bash scripts/demo/start.sh
```

El reinicio termina las sesiones de Lumen; volver a entrar con Verify.

El instalador añade:

- Política `lumen-personal-user` y grupo interno `lumen-personal-users`, con
  las tres entidades humanas de la demo.
- Techos `lumen-personal-read` o `lumen-personal-write` a los registros OBO,
  conservando sus techos y bloqueos anteriores. No concede estos permisos
  como políticas autónomas a los agentes.
- Un secreto ficticio `demo` por usuario, solo si nunca ha existido. Conserva
  valores, versiones y secretos eliminados al repetir.
- Catálogo de identidades y políticas en `secrets/chatbot/personal-spaces`.
  El bootstrap puede leer ese catálogo, pero no los valores personales.

Los reconciliadores de agentes y grupos reaplican la extensión si ya estaba
instalada. Utiliza el mount KV v2 `secrets` y un prefijo independiente,
`lumen-personal`; no crea motores ni namespaces por persona.

## Política y alcance

La misma política central se aplica a los tres usuarios:

```hcl
path "secrets/data/lumen-personal/{{identity.entity.id}}/*" {
  capabilities = ["create", "read", "update"]
}
path "secrets/metadata/lumen-personal/{{identity.entity.id}}/*" {
  capabilities = ["list"]
}
path "secrets/metadata/lumen-personal/{{identity.entity.id}}" {
  capabilities = ["list"]
}
```

Vault resuelve la plantilla con la entidad **humana** del flujo OBO. La ruta
real contiene su UUID. Cambiar de agente conserva el mismo espacio.

## De dónde sale `identity.entity.id` y cómo llega a la autorización

Hay dos identidades distintas: la persona que delega y el agente que actúa.
El UUID que organiza el espacio personal es el de la **persona en Vault**,
no el ID de usuario de Verify ni el UUID de la entidad del agente.

| Momento | Qué ocurre | Dónde comprobarlo |
|---|---|---|
| Preparar las identidades | `05-sync-groups.sh` crea `chatbot-human-<ID de Verify>`; Vault asigna su UUID. El alias vincula `issuer` de Verify y `external_id` del usuario con ese UUID en `canonical_id`. | Entidad y alias humanos de Vault; el perfil OAuth `verify` identifica al emisor. |
| Preparar el espacio | `configure-personal-spaces.py` lee ese UUID y publica el catálogo que usa Lumen. Añade la entidad al grupo `lumen-personal-users`, que asigna `lumen-personal-user`. | Catálogo `secrets/chatbot/personal-spaces`, grupo y política en el namespace `verify`. |
| Crear el primer secreto | El instalador escribe el dato ficticio `demo` en `secrets/data/lumen-personal/<UUID humano>/demo` con su credencial de aprovisionamiento. Las escrituras posteriores desde la pantalla usan OBO. | Ruta KV v2. El campo `owner` del JSON solo describe el dato; no establece su propietario de seguridad. |
| Obtener la delegación | Lumen presenta a Verify el token humano, el token del agente y el RAR de la operación. El JWT OBO firmado contiene `sub` humano, `actor-token.sub` del agente y `authorization_details`. | Intercambio OBO y JWT de esta ejecución en la traza. |
| Acceder a Vault | Lumen envía ese JWT en `X-Vault-Token`. Vault lo valida y usa `user_claim=sub` y `actor_claim=actor-token.sub` del perfil OAuth para resolver ambos alias por separado. El alias humano conduce a su `canonical_id`. | Perfil OAuth `verify`, alias humanos y del agente, petición a Vault. |
| Decidir | Vault expande la plantilla con el UUID humano y exige **políticas humanas ∩ techo del agente ∩ RAR**. La ruta solicitada no decide quién es el usuario. | Respuesta de Vault y auditoría correlacionada con `request_id`. |

Por ejemplo, con un humano `A` y un agente cuyo techo contiene
`secrets/data/lumen-personal/*`, la política humana se expande a
`secrets/data/lumen-personal/A/*`. Pedir `secrets/data/lumen-personal/B/demo`
en el RAR no cambia `A` por `B`: el alias se resuelve desde la identidad del
token. En la configuración de esta demo, Vault deniega el acceso ajeno aunque
Verify haya emitido el JWT OBO con HTTP 200.

El wildcard del Registry permite que el mismo agente atienda espacios de varias
personas. Cada llamada sigue limitada por la política de la persona concreta.
Incluso con ruta propia, el techo de Consulta o Revelado impide escribir.

| Usuario | Estándar | Consulta | Creación | Revelado |
|---|---|---|---|---|
| Reader | Leer y guardar propios | Leer propios | Leer y guardar propios | Leer propios |
| Writer | Leer y guardar propios | Leer propios | Leer y guardar propios | Leer propios |
| Supervisor | Leer y guardar propios | Leer propios | Leer y guardar propios | Leer propios |
| Acceso a otro propietario | Denegado | Denegado | Denegado | Denegado |

Esta matriz corresponde al espacio personal. Reader sigue sin crear solicitudes
compartidas; Supervisor sigue sujeto a su techo de revelado. Cada propietario
recibe permiso central sobre sus secretos de prueba y el agente puede reducirlo
a lectura. No se habilita borrado desde esta pantalla.

## Comprobación desde la interfaz

1. Entra con **Reader + Estándar** y abre **Mi espacio de secretos** en el menú.
2. Conserva el nombre `demo` y pulsa **Leer secreto**: HTTP 200 y un valor
   ficticio cuyo propietario es `lumen-reader`.
3. Pulsa **Listar mi espacio**: aparecen nombres dentro de tu UUID.
4. Cambia la nota JSON y pulsa **Guardar versión**. Un nombre nuevo permite
   crear otro secreto. Para modificar uno existente, léelo antes: la escritura
   lleva `options.cas`; una versión antigua recibe HTTP 400 sin sobrescribir.
5. En **Comprobar aislamiento entre usuarios**, selecciona Writer o Supervisor
   y pulsa **Intentar leer el espacio ajeno**: debe devolver HTTP 403.
6. Abre **Ver petición y resultado**. Comprueba el usuario OBO, el agente,
   la ruta ajena en `authorization_details`, los IDs de las entidades y el 403
   de Vault. Lumen no simula el rechazo ni omite esa ruta del RAR.
7. Cambia al agente **Consulta** y autentica de nuevo el mismo usuario. Su UUID
   y valores se conservan. Leer funciona; guardar devuelve HTTP 403 por el techo.
8. Repite como **Supervisor**: no permite leer los secretos personales de Reader.

**Por qué Vault permite o deniega** muestra el HCL publicado por el instalador,
con enlaces a las políticas y entidad actuales en Vault. Las peticiones reales
son la prueba del acceso efectivo. Los enlaces usan tu sesión de Vault sin
tokens en la URL.

En la traza, **Aislamiento del espacio personal** desarrolla este recorrido en
cuatro pasos y muestra, en español o inglés:

- La persona que delega y el propietario de la ruta, con sus UUID separados.
- `issuer`, `sub / external_id`, `canonical_id` y el cliente del agente registrados.
- La plantilla humana, su expansión con el UUID del usuario y la ruta solicitada.
- El resultado del servicio seleccionado. Un HTTP 200 de Verify solo acredita
  la emisión del token; selecciona la llamada a Vault para ver el acceso.
- **Por qué hay un wildcard en el Registry**: HCL humano y techo personal del
  agente conservados en la traza, más tipo, ruta y capacidades del RAR.
- **Origen de los datos y cómo comprobarlo**: procedencia y puntos de consulta
  en Vault, junto a enlaces a la documentación oficial.

Los nombres, UUID y HCL son snapshots del catálogo aprovisionado que Lumen
registra al ejecutar la operación. La expansión mostrada es una explicación de
la regla de la demo, **no una consulta a la ACL efectiva ni una evaluación de
todas las políticas de Vault**. Cambios posteriores pueden hacer que el catálogo
no coincida con la configuración actual. La respuesta real de Vault sigue siendo
la evidencia del acceso observado. Un 403 no identifica por sí solo todas las
reglas que intervinieron; una ruta ajena permitida se señala para revisar políticas.

Las trazas antiguas conservan sus IDs y muestran «No registrado» cuando falta
información; no se completan con la configuración actual. Genera una nueva
operación para obtener los campos nuevos. El panel no muestra tokens ni valores
de secretos: siguen disponibles en los controles sensibles y la consola de esa
misma llamada.

HTTP 404 indica un secreto inexistente; HTTP 400 puede señalar conflicto de
versión. Ninguno se presenta como prueba de aislamiento. Las capturas sensibles
y la consola de repetición incluyen token, cuerpo y respuesta reales, con los
controles y retención existentes del laboratorio.

La auditoría general registra estas rutas con HMAC. No se amplían los filtros
raw especializados de otros motores. La traza de Lumen conserva la captura
según `LUMEN_TRACE_VAULT_RAW`; su `request_id` permite correlacionar la auditoría.

## Verificación repetible

```bash
bash chatbot/scripts/verify-personal-spaces.sh
```

Ejecuta Authorization Code + PKCE para tres usuarios y cuatro agentes. Comprueba
lectura/listado propios, techos de escritura, lectura posterior, conflicto CAS
y denegaciones de lectura/listado/escritura entre propietarios. Solo escribe
valores ficticios en `verification`. Los tokens quedan en el directorio privado
de estado. El [informe](../../chatbot/docs/personal-spaces-verification.json)
contiene resultados, rutas y trazas, sin valores secretos.

Referencias: [plantillas de políticas](https://developer.hashicorp.com/vault/docs/concepts/policies#templated-policies),
[OBO](https://developer.hashicorp.com/vault/ai/iam/setup-obo) y
[KV v2 y CAS](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2).

## Capturas actuales

La [revisión del 22/10](../runs/20261022T140230Z-workspace-review/README.md) comprobó lectura propia y denegación de acceso cruzado con la interfaz actual.

![Lectura del secreto ficticio propio](../screenshots/current/personal-space-read.jpg)

![Vault deniega el espacio de otro usuario](../screenshots/current/personal-space-denied.jpg)

### Explicación visual del aislamiento

La revisión del 22/10 comprobó el panel actual en español, inglés y a 390 px.
Supervisor con Consulta leyó su espacio (200) y Vault rechazó el de Reader (403).
El panel distingue el UUID humano del propietario solicitado y muestra cómo se
expande la política; la respuesta de Verify no se confunde con permiso de Vault.

![Identidad, política y ruta del acceso denegado](../screenshots/current/personal-isolation-trace.jpg)

[Versión en inglés](../screenshots/current/personal-isolation-en.jpg) ·
[Vista móvil](../screenshots/current/personal-isolation-mobile.jpg).
