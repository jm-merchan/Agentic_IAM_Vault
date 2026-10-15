# Bloquear accesos durante la demostración

Con Vault y Lumen activos, ejecuta desde la raíz del workspace:

```bash
./demo.sh blocks
./demo.sh block xai
./demo.sh unblock xai
./demo.sh block database-read
./demo.sh unblock database-read
./demo.sh block database-write
./demo.sh unblock database-write
./demo.sh block decrypt
./demo.sh unblock decrypt
```

Los comandos usan la conexión administrativa generada al inicializar Vault. No requieren añadir secretos a `.env`, reiniciar la aplicación ni volver a entrar en Verify. El alcance es Lumen en el namespace `verify`, para todos sus usuarios. `unblock` retira únicamente ese bloqueo adicional: conserva las restricciones de grupos, RAR y políticas de base. Varios bloqueos pueden coexistir.

| Control | Rutas denegadas en Vault | Efecto visible |
|---|---|---|
| `xai` | `xai/creds/lumen`, `secrets/data/chatbot/xai-access` | Un nuevo mensaje libre recibe un HTTP 403 de Vault antes de invocar el LLM. Los botones que consultan datos directamente siguen funcionando. |
| `database-read` | `database/creds/chatbot-readonly` y `database/creds/chatbot-readwrite` | Fallan catálogo, inventario y solicitudes; tampoco se emiten credenciales RW que permitirían eludir el bloqueo de lectura. |
| `database-write` | `database/creds/chatbot-readwrite` | El gestor puede consultar con RO, pero Guardar solicitud recibe 403. |
| `decrypt` | `transit/decrypt/lumen-applications`, `transform/decode/lumen-dni`, `transform/decode/lumen-iban` | El supervisor ve la lista enmascarada, pero no puede revelar los datos. Cifrado y tokenización permanecen disponibles para el gestor. |

MySQL tiene roles RO y RW, no un rol de escritura sin lectura. Por eso bloquear toda lectura implica bloquear ambos roles. La aplicación usa RO para todos los SELECT, incluido el gestor, y RW solo cuando guarda.

## Qué cambia realmente en Vault

Hay cuatro políticas independientes: `lumen-block-xai`, `lumen-block-database-read`, `lumen-block-database-write` y `lumen-block-decrypt`. Normalmente contienen solo un comentario. Al bloquear escritura, por ejemplo, el comando guarda en `lumen-block-database-write`:

```hcl
path "database/creds/chatbot-readwrite" {
  capabilities = ["deny"]
}
```

El `deny` prevalece sobre el permiso de la política de base. RAR debe permitir la ruta, pero nunca puede superar una denegación de la política. No se edita el JWT ni se espera a que caduque: las nuevas peticiones se evalúan contra la política actual de Vault. [Políticas de Vault](https://developer.hashicorp.com/vault/docs/concepts/policies) · [RAR](https://developer.hashicorp.com/vault/ai/iam/concepts/rar/enforcement).

La asociación depende del flujo:

- **xAI autónomo:** `lumen-block-xai` forma parte de las políticas de la entidad `chatbot-xai`. Es lo que limita Client Credentials.
- **MySQL y protección de datos OBO:** los tres bloqueos forman parte de `ceiling_policies` del agente `chatbot-oidc`. Vault comprueba tanto los permisos del usuario como ese límite del actor. Las políticas límite del registro se aplican a OBO; por sí solas no bloquean el acceso autónomo. [Agent registry](https://developer.hashicorp.com/vault/ai/iam/concepts/agent-registry).

`start` conserva las políticas de bloqueo existentes. `remove` elimina el Vault de la demo; el siguiente `start` crea las cuatro políticas inactivas. Las verificaciones de funcionamiento normal presuponen que no hay bloqueos: consulta `./demo.sh blocks` antes de ejecutar `verify`.

Para inspeccionar la política desde la CLI:

```bash
(
  source ~/.local/state/lumen-vault-demo/vault/config.env
  export VAULT_ADDR VAULT_TOKEN VAULT_CACERT
  vault policy read -namespace=verify lumen-block-database-write
  vault read -namespace=verify agent-registry/registration/display-name/chatbot-oidc
)
```

Si usas `LUMEN_STATE_DIR`, sustituye la ruta del ejemplo. En la UI de Vault selecciona el namespace `verify` y abre Policies → ACL Policies.

## RAR y claves xAI en caché

Verify recibe `authorization_details` en Client Credentials y devuelve un JWT firmado con estas dos rutas:

```json
[
  {"type":"vault:path_access","path":"xai/creds/lumen","capabilities":["read"]},
  {"type":"vault:path_access","path":"secrets/data/chatbot/xai-access","capabilities":["read"]}
]
```

Lumen valida la firma, issuer, caducidad, identidad del cliente y coincidencia exacta del RAR. El registro de `chatbot-xai` exige RAR; no hay fallback a un JWT sin esa restricción.

Antes de cada ejecución se lee `chatbot/xai-access` con ese JWT. Este registro contiene únicamente una generación de caché, no una API key. Su ACL permite que Vault deniegue también una ejecución que habría reutilizado una clave vigente. La clave se reutiliza mientras cubra el presupuesto de la ejecución y el margen de caducidad; el bloqueo no exige emitir una clave nueva por cada mensaje.

`block xai` instala primero el deny y revoca de forma síncrona los leases `xai/creds/lumen/`. `unblock xai` cambia la generación antes de retirar el deny. Así, incluso si nadie envía un mensaje durante el bloqueo, una clave revocada no se reutiliza después. Un fallo de revocación devuelve error y deja el deny activo; no se usa `revoke-force`.

En Vault 2.1.2 de esta imagen, `/sys/capabilities-self` rechazó los JWT externos durante la comprobación. Por eso esta versión utiliza una lectura KV real para reautorizar la caché, en lugar de presentar una comprobación de capacidades como si hubiera funcionado.

## Recorrido en la interfaz

1. **xAI:** escribe una pregunta general. Ejecuta `block xai` y envía otra: aparece la ruta denegada y HTTP 403. Ejecuta `unblock xai` y repite: se obtiene una clave nueva y vuelve la respuesta.
2. **Lectura:** entra como lector o gestor. Abre Planes de energía, ejecuta `block database-read` y pulsa otra vez el botón. Tras `unblock database-read`, repite sin cerrar sesión.
3. **Escritura:** entra como gestor y completa una solicitud ficticia hasta Revisar. Ejecuta `block database-write` y pulsa Guardar solicitud. La lectura sigue disponible; el INSERT no llega a MySQL. Ejecuta `unblock database-write` y reintenta.
4. **Descifrado:** entra como supervisor. Abre Solicitudes, ejecuta `block decrypt` y pulsa Revelar datos. La lista permanece enmascarada. Tras `unblock decrypt`, la misma operación vuelve a funcionar.

`Comprobar límites en Vault` hace peticiones reales a las nueve rutas SQL/Transit/Transform. La columna Esperado describe los permisos normales del perfil; un bloqueo administrativo produce una diferencia deliberada entre esa columna y Resultado.

En cada acción, **Ver última traza → Ver en Grafana** permite seguir el JWT/RAR, la ruta y la respuesta. En un bloqueo xAI no debe aparecer `xai.chat`; al bloquear una lectura SQL no debe aparecer `mysql.query`. En el formulario bloqueado puede aparecer el SELECT previo para comprobar duplicados, pero no el INSERT. Los cambios administrativos quedan también en la auditoría de Vault (`sys/policies/acl/lumen-block-*` y, cuando corresponda, `sys/leases/revoke-prefix/*`).

## Límites del bloqueo

Se bloquean las peticiones posteriores a Vault y se revocan los leases de las rutas SQL/xAI afectadas. Una petición ya en curso, una conexión MySQL ya abierta o información que el navegador ya haya mostrado no se deshacen. El comando no borra el historial del chat ni el texto ya revelado. Para comprobar de nuevo una lectura, usa el botón correspondiente: el modelo puede recordar información recibida antes del bloqueo.

El root token administrativo no queda bloqueado por estas políticas de Lumen. La aplicación no recibe ese token ni puede modificar las políticas.

## Validación

[Prueba real xAI](../chatbot/docs/xai-rar-block-verification.json): JWT sin RAR y con RAR incorrecto denegados; mismo JWT permitido → bloqueado → permitido; token nuevo también denegado durante el bloqueo; lease emitido revocado. Se puede repetir con `bash chatbot/scripts/test-xai-block.sh` después de exportar `VAULT_ENV_FILE` apuntando a la conexión generada. La prueba requiere xAI inicialmente desbloqueado y lo deja desbloqueado.

Validación del 15 de octubre: **96 tests y dos subcasos**, ocho comprobaciones reales de RAR/bloqueo xAI, doce del ciclo de vida xAI y doce peticiones OBO repetidas con los mismos JWT anteriores al bloqueo. En Chrome se verificó xAI permitido/bloqueado/restaurado, una consulta SQL denegada, Guardar solicitud denegado y después completado con la misma referencia, y Revelar datos denegado/restaurado. Todos los controles quedaron desbloqueados al terminar.

[Resumen](runs/20261015-rar-blocks/summary.json) · [JWT anteriores al bloqueo](runs/20261015-rar-blocks/previous-jwt-checks.json) · [IDs de trazas por escenario](runs/20261015-rar-blocks/ui-traces.json) · [Correlación de auditoría](runs/20261015-rar-blocks/observability.json).

Se comprobaron 11 trazas, 159 spans y 41 operaciones de Vault contra sus 82 eventos originales de petición/respuesta. **Loki conserva una limitación de ingestión:** faltan copias raw completas para dos operaciones Transit decrypt (la prueba inicial del gestor y la denegación del supervisor). Los pares originales están completos en los logs de los pods de Vault; el informe mantiene `loki_raw_all_passed=false` y no presenta la correlación raw de Loki como completa. Las trazas nuevas de autorización xAI sí incluyen la ruta añadida a la auditoría.

### Capturas actuales

La traza xAI bloqueada termina en HTTP 403 y no invoca el LLM:

![RAR xAI y rechazo de Vault antes del LLM](runs/20261015-rar-blocks/screenshots/xai-blocked-trace.jpg)

[La misma traza en Grafana: seis spans y rechazo en vault.read, sin llamada al modelo](runs/20261015-rar-blocks/screenshots/grafana-xai-blocked.jpg).

El gestor conserva el formulario para reintentar después de `unblock database-write`:

![Guardar solicitud denegado por Vault](runs/20261015-rar-blocks/screenshots/database-write-blocked.jpg)

[Solicitud guardada después de desbloquear](runs/20261015-rar-blocks/screenshots/database-write-restored.jpg).

El supervisor no puede recuperar los datos con `decrypt` bloqueado:

![Descifrado denegado para el supervisor](runs/20261015-rar-blocks/screenshots/decrypt-blocked.jpg)

[Descifrado restaurado — todos los valores son ficticios](runs/20261015-rar-blocks/screenshots/decrypt-restored.jpg) · [Lectura SQL bloqueada](runs/20261015-rar-blocks/screenshots/database-read-blocked.jpg) · [Clave xAI reutilizada con reautorización](runs/20261015-rar-blocks/screenshots/xai-rar-reuse.jpg) · [xAI recuperado](runs/20261015-rar-blocks/screenshots/xai-restored.jpg).
