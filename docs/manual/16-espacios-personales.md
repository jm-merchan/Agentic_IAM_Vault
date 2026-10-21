# 16 · Espacios de secretos por usuario

**Mi espacio de secretos** añade un laboratorio de KV v2 con OBO y aislamiento
por identidad humana, en el namespace `verify`. Conserva la bandeja compartida,
MySQL, Transit, Transform y las credenciales de los modelos. Estos valores no
se envían al LLM.

## Preparación

Después de `grupos`, ejecutar desde la raíz del repositorio:

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
