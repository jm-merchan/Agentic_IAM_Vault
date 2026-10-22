# 17 · Contratar un borrador con CIBA

Las solicitudes guardadas son **borradores**. Writer puede formalizar uno propio
con **Contratar**, usando Estándar o Creación de solicitudes. Validador confirma
en IBM Verify; solo después se escribe el estado protegido en MySQL. El Writer
propietario puede descargar el contrato PDF, también en sesiones posteriores.

Esta extensión sustituye el experimento de aprobación de PDF para Supervisor.
Supervisor conserva el revelado habitual mediante OBO. No hay Control Groups.
El contrato es ficticio: no constituye una contratación comercial ni un cobro.

## Preparar y habilitar

Desde la raíz del repositorio, después de agentes, grupos y MySQL:

```bash
bash chatbot/scripts/configure-contracts.sh
```

El instalador carga las variables por sí mismo y conserva el Validador seleccionado.
En este tenant es la cuenta existente `jose.merchan@ibm.com@www.ibm.com`
(ID `64300857U3`), que recibe la petición por correo. Conserva su contraseña,
perfil y privilegios administrativos. Para seleccionar otra cuenta existente:

```bash
bash chatbot/scripts/configure-contracts.sh --validator 'usuario@dominio.example'
```

Sin selección previa prepara `lumen-validator`, con correo ficticio: **no puede
recibir un OTP por correo**. Antes de verificar, elige una cuenta real o configura
su método de autenticación en Verify. El instalador no presupone push al móvil.
Cambiar de cliente CIBA o Validador deshabilita la función hasta verificarla otra vez.

La prueba siguiente inicia sesión como Writer, crea **un borrador ficticio** y
envía una petición a Validador. Comprueba el texto `Lumen contrato …` antes de
confirmarlo en Verify. Este script espera la aprobación; no la sustituye:

```bash
bash chatbot/scripts/verify-contracts.sh
```

Si termina correctamente escribe `chatbot/docs/contracts-verification.json`
y `output/pdf/lumen-contrato-verificado.pdf`. Luego:

```bash
bash chatbot/scripts/configure-contracts.sh --enable
```

```bash
bash scripts/demo/start.sh
```

El reinicio termina las sesiones de Lumen. Entra de nuevo. `./demo.sh start`
y el paso guiado `contratacion` preparan la extensión, conservando la activación
si el cliente y Validador siguen siendo los verificados. Una instalación nueva
queda deshabilitada hasta completar la prueba real.

## Verificación en la interfaz

1. Entra como **Writer + Estándar** o **Writer + Creación de solicitudes**.
2. Crea una solicitud con los datos ficticios y pulsa **Guardar borrador**.
3. Abre **Solicitudes**. Solo tus borradores muestran **Contratar**.
4. Pulsa **Contratar**. La ventana muestra Validador, la referencia y el mensaje
   que debe coincidir con Verify. Mientras espera no existe una fila de contrato.
5. Validador confirma en Verify. Si rechaza o caduca, el borrador se conserva.
6. Tras el commit aparece **Descargar contrato PDF**. La bandeja muestra
   `contratada`, la fecha y el botón de descarga.
7. La ventana muestra un único enlace a la última traza CIBA; al terminar se
   llama **Ver traza de contratación**. Selecciona CIBA, login de Vault, credencial SQL
   y `CALL lumen_contracts.formalize` para inspeccionar cada intercambio.
8. Cierra sesión y vuelve a entrar como el mismo Writer: el PDF sigue disponible.

Cerrar el diálogo detiene el sondeo. **Ver contratación pendiente** lo reabre.
Una petición pendiente vive en memoria como máximo diez minutos; un reinicio
requiere pedir otra. Los contratos confirmados y sus PDFs persisten.

## Quién autoriza cada paso

| Paso | Identidad y credencial | Control |
|---|---|---|
| Leer/guardar borrador | Usuario Writer + agente, JWT OBO | Vault aplica políticas humanas ∩ techo del agente ∩ RAR. |
| Solicitar CIBA | Cliente confidencial `vault-chatbot-contract` → Verify | Lumen vincula `auth_req_id` al Writer, agente, borrador y hash de su contenido. |
| Confirmar | Validador → Verify | El cliente solo admite CIBA; los demás grants, incluido client_credentials, están deshabilitados. |
| Login en Vault | ID token de Validador → `auth/ciba-contract/login` | Vault valida firma, issuer, audience exclusiva del cliente CIBA y subject exacto de Validador. |
| Obtener credencial SQL | Token nativo Vault → `database/creds/chatbot-contract` | Política `lumen-contract-confirm`, asignada al token, nunca al grupo/entidad OBO. |
| Formalizar | Usuario SQL temporal → `CALL lumen_contracts.formalize` | Solo EXECUTE; el procedimiento valida propietario y snapshot, inserta y confirma. |
| Publicar PDF | Token nativo Vault → KV v2 | Tras commit, PDF bajo `lumen-contracts/<entidad humana Writer>/<contract_id>`. |
| Descargar | Writer propietario + agente, JWT OBO | Política `lumen-contract-owner` con `{{identity.entity.id}}`, techo del agente y RAR de lectura. |

**El login CIBA es autenticación JWT nativa de Vault, no OBO.** La traza lo indica
expresamente y no le atribuye el agente de la sesión. El cambio no eleva los
permisos del Writer ni de su agente: una operación separada utiliza la confirmación
de otra identidad. CIBA autentica y obtiene confirmación; Lumen mantiene el vínculo
con el borrador. Vault no interpreta el texto del mensaje ni decide qué contrato
firmar, y MySQL no valida directamente el JWT.

## Campo protegido y permisos SQL

El campo autoritativo es **`lumen_contracts.contracts.status = 'contratada'`**.
Se usa una base separada porque el rol Writer existente tiene permisos sobre
`scripting.*`. No puede escribir en `lumen_contracts`.

La tabla original `scripting.energy_applications` conserva sus datos y su estado
histórico. La bandeja obtiene el estado visible mediante un LEFT JOIN: sin
contrato es `borrador`; con contrato muestra el estado protegido. No se convierten
automáticamente borradores existentes.

El usuario temporal `chatbot-contract` solo recibe EXECUTE del procedimiento.
Su cuenta definer está bloqueada para login y tiene los permisos de lectura,
inserción y bloqueo necesarios. El bloqueo FOR UPDATE requiere también UPDATE;
se limita a las columnas identificadoras de las tablas leídas. Esos permisos
no se entregan a Writer ni al usuario SQL temporal.

El procedimiento bloquea el borrador y la tarifa, verifica su hash y propietario,
y guarda referencia, solicitante, Validador, fecha, tarifa, hashes y PDF cifrado.
La clave primaria de application_id hace idempotentes los reintentos. Un trigger
impide actualizar un borrador contratado y la FK impide borrarlo. La credencial
ordinaria solo puede leer columnas públicas del registro; no su PDF cifrado.

El PDF usa Transit `lumen-contracts` para su copia cifrada en MySQL. La copia de
descarga en KV contiene el PDF codificado en base64; KV aporta cifrado en reposo
y ACL por propietario. Base64 **no es cifrado**. Lumen comprueba su SHA-256 contra
MySQL al descargar. El logo está arriba a la derecha; razón social, CIF y sede son
ficticios. El contenido no se envía al LLM.

## Límites, errores y recuperación

- El token Vault dura como máximo 120 s; la credencial SQL, 60 s por defecto y
  120 s como máximo. Lumen revoca el token y sus leases al acabar.
- Los bloqueos `database-read`, `database-write` y `decrypt` también limitan
  la operación CIBA. Los comandos de bloqueo de base de datos también revocan
  los leases SQL correspondientes. Editar solo una ACL no revoca una credencial
  SQL ya emitida; esa credencial sigue su lease o la revocación del token.
- El bloqueo de descifrado impide preparar contratos nuevos, pero no retira PDFs
  ya publicados en el espacio del Writer ni copias ya descargadas.
- Sin CIBA, el token de login ordinario falla en el mount JWT y el OBO de Writer
  falla al pedir el rol SQL de contratación. Las pruebas verifican ambos.
- CIBA no produce por sí solo un JWT de un uso ni una autorización SQL por fila.
  La credencial permite ejecutar el procedimiento durante su vida útil; **Lumen**
  vincula la aprobación al borrador y al snapshot. Un operador con acceso a las
  credenciales capturadas del laboratorio puede repetir llamadas dentro de ese
  alcance. Administradores de Vault/MySQL también quedan fuera de esta barrera.
- Un cambio del borrador durante la espera impide formalizar el snapshot antiguo.
  El rechazo no crea un contrato.
- La limpieza periódica respeta una confirmación en curso; la operación comprueba
  la caducidad antes de formalizar y conserva el snapshot hasta terminar. Una
  cancelación marca la petición como error y elimina su estado sensible. Si ya
  había un commit en curso, actualiza la bandeja para conocer el resultado persistido.
- Si hay commit pero falla la publicación KV, el contrato ya existe. Actualiza
  la bandeja, intenta descargar y usa **Recuperar PDF con CIBA**. El procedimiento
  devuelve el contrato original y se publica su PDF original, sin duplicarlo.
- La descarga se limita al Writer propietario; Reader y Supervisor no reciben
  acceso a estos PDFs por su rol. Se comprueba que la sesión siga vigente y sea
  la misma tras esperar el bloqueo y antes de entregar el PDF. Supervisor conserva
  el revelado de solicitudes.
- La consola de trazas conserva las peticiones reales cuando la captura está
  activada. Repetir una credencial revocada o un código consumido devuelve el error
  real del servicio. No se renueva automáticamente para simular éxito.

Las pruebas reales y su fecha están en
[contracts-verification.json](../../chatbot/docs/contracts-verification.json).
Son evidencia de esa ejecución, no una garantía sobre cambios posteriores.

El [ensayo del 22/10/2026](../runs/20261022T122934Z-full-e2e/README.md) incluye
aprobación real del Validador, nueve comprobaciones correctas, un único commit
idempotente y dos descargas del backend con el mismo SHA-256. Chrome mostró el
contrato persistido después de reiniciar y ejecutó su botón PDF; la recepción
del archivo en el navegador no quedó confirmada por la herramienta.

## Referencias

- [IBM Verify SaaS: iniciar CIBA](https://docs.verify.ibm.com/verify/v2.0/reference/post_oauth2-ciba).
- [OpenID CIBA Core](https://openid.net/specs/openid-client-initiated-backchannel-authentication-core-1_0.html).
- [Vault: JWT auth y restricciones de claims](https://developer.hashicorp.com/vault/api-docs/auth/jwt).
- [MySQL: locking reads y privilegios](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html).

La retirada de la demo incluye sus clientes CIBA y el grupo `chatbot-validators`, identificado por la marca `externalId=lumen-demo:contract-validators`. Conserva la cuenta real elegida como Validador. Solo las cuentas ficticias `lumen-*` con correo `@example.invalid` entran en el inventario de borrado. El antiguo cliente del experimento PDF queda deshabilitado al migrar.
