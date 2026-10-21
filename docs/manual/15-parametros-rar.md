# 15 · Parámetros RAR: relacionar reglas, peticiones y decisiones de Vault

Abrir **Laboratorio RAR** desde la barra lateral de Lumen o desde el panel
**Agentes por tarea**. Es una página opcional: elegir un escenario no cambia
la autorización del chat ni instala restricciones globales. Las llamadas solo
se realizan al pulsar **Comparar peticiones reales**.

## Qué se compara

Cada caso envía el mismo cuerpo a la misma ruta con el mismo usuario y agente:

1. **Control sin parámetros:** token OBO con ruta exacta y capacidad `update`.
2. **Con parámetros RAR:** otro token OBO para esa ruta y capacidad, añadiendo
   las restricciones del escenario.

Los dos tokens se obtienen de Verify. Lumen comprueba firma, issuer, caducidad,
usuario, actor y coincidencia exacta de `authorization_details`, incluidos los
parámetros. Si Verify omite o cambia una restricción, no se envía ese token a
Vault. Vault evalúa los permisos de usuario, el techo del agente y el RAR.

La tabla presenta resultados reales, no una simulación de políticas:

| Control | Con restricciones | Interpretación |
|---|---|---|
| 200 | 200 | La petición ha sido admitida con las restricciones. |
| 200 | 403 | La comparación demuestra una denegación al añadir el RAR. |
| 403 | 403 | El acceso ya falla sin parámetros; revisar usuario, techo y bloqueos. No atribuir el resultado a la regla RAR. |
| 200 | 200, cuando se esperaba denegación | La restricción no se ha aplicado como se esperaba; se señala la discrepancia. |
| Error de Verify, conexión o motor | Cualquier resultado | No concluyente; no se cuenta como una denegación RAR demostrada. |

El control conserva las restricciones de ruta y capacidad: no utiliza un token
administrativo ni modifica las ACL. Se cifran datos ficticios; Transform crea
tokens de prueba. El escenario de revelado descifra dos perfiles sintéticos.
No se modifican solicitudes ni filas de MySQL y no se llama al LLM.

## Seis escenarios

| Escenario | Restricciones | Casos | Combinación recomendada |
|---|---|---|---|
| Versión de cifrado permitida | `allowed_parameters` | Versión `"1"`, versión `"0"`, campo `context` extra y número `1` frente a cadena `"1"`. | Writer + Creación o Estándar |
| Prohibir lotes | `denied_parameters: {"batch_input": []}` | Un dato permitido; un lote denegado. | Writer + Creación o Estándar |
| Versión explícita | `required_parameters: ["key_version"]` | Presente, omitida y otro valor presente. | Writer + Creación o Estándar |
| Combinación | Los tres campos | Cumplimiento, `deny` sobre un valor también permitido, parámetro omitido y valor fuera de la lista. | Writer + Creación o Estándar |
| Transformación explícita | `required_parameters: ["transformation"]` | Nombre presente o deducible por el motor pero omitido en el cuerpo. | Writer + Creación o Estándar |
| Un único perfil revelable | `allowed_parameters` sobre `ciphertext`, con `required_parameters` | Perfil aprobado frente a otro ciphertext válido. | Supervisor + Revelado o Estándar |

Los primeros cuatro escenarios usan `transit/encrypt/lumen-applications`; el
quinto, `transform/encode/lumen-dni`; el sexto,
`transit/decrypt/lumen-applications`. La UI muestra el cuerpo exacto de cada
variante y el JSON de los tres campos, incluso cuando alguno no se utiliza.

`[]` tiene significados distintos: en `allowed_parameters` admite cualquier
valor de ese campo; en `denied_parameters` prohíbe el campo con cualquier valor.
`required_parameters` exige presencia; por sí solo no exige un valor concreto.
En el escenario combinado la denegación prevalece sobre el valor permitido.

La prueba en **Vault 2.1.2+ent** observó que el número JSON `1` no coincidía con
la cadena `"1"` de la lista permitida, aunque Transit aceptaba ambos en el control.
No se normalizan los tipos en el cliente: la UI muestra el JSON exacto y el
resultado real para poder detectar cambios de comportamiento entre versiones.
Las restricciones actúan sobre parámetros de la petición; no se presenta este
laboratorio como un filtro de filas SQL ni como una inspección recursiva de
cualquier objeto JSON anidado.

## Trazas y consola de peticiones

Cada fila ofrece **Ver control** y **Ver restricción**. El enlace selecciona la
llamada correspondiente a Vault en la traza. Sus pasos conservan escenario,
caso, fase, agente, HTTP y Request ID cuando el servidor lo devuelve.

Debajo del diagrama se muestran el `authorization_details` de esa fase y el
cuerpo sintético enviado a Vault. En el intercambio OBO se muestra el RAR
validado; en la llamada a Vault, el claim presentado. Esta proyección no convierte
la decodificación de un JWT en una validación de su firma.

**Ver valores sensibles** y **Abrir consola de peticiones** conservan la captura
real: Basic del cliente, subject/actor tokens, JWT OBO, cabeceras, cuerpo y respuesta.
La consola permite repetir esa petición con el token capturado; no lo renueva.
Los tokens pueden haber caducado al repetirlos. Las trazas solo se abren desde
la sesión que las generó. Los resultados del laboratorio permanecen al navegar
o cambiar ES/EN dentro de esa sesión; al cambiar de agente se inicia otra sesión.

## Preparación y repetición

`./demo.sh start` reconcilia el esquema mediante `configure-base.sh` y prepara
los perfiles ficticios durante el registro de agentes. La instalación manual
incorpora ambos pasos en los capítulos 03 y 05. Para añadirlo a una instalación
existente, desde la raíz del proyecto:

```bash
bash -c 'source scripts/demo/common.sh; load_inputs; bash chatbot/scripts/configure-rar-lab.sh'
```

El esquema anterior conocido se amplía con tres propiedades opcionales. Se
conservan ID, consentimiento, descripción y demás campos. Un esquema personalizado
desconocido detiene la migración. No se cambian clientes OAuth, usuarios, ACL,
techos ni versión de Vault. Repetir la preparación conserva los perfiles de prueba.
También está disponible como paso `rar-parametros` del instalador guiado.

Para cargar los cambios en Lumen, reiniciar únicamente la aplicación y sus
túneles de observabilidad; el reinicio cierra las sesiones actuales:

```bash
bash scripts/demo/start.sh
```

Verificación reproducible con los usuarios ficticios existentes, login PKCE real,
OBO y peticiones reales a Vault:

```bash
bash chatbot/scripts/verify-rar-parameters.sh
```

El informe [rar-parameters-verification.json](../../chatbot/docs/rar-parameters-verification.json)
contiene códigos HTTP, combinación utilizada y referencias de trazas, sin tokens
ni contraseñas. Incluye Writer + Creación, Supervisor + Revelado,
Supervisor + Consulta y Writer + Estándar. Las trazas de esa prueba por script
se conservan en el directorio privado de estado, separadas de las sesiones UI.

La [verificación de interfaz](../../chatbot/docs/rar-parameters-ui-verification.json)
recoge pruebas en Chrome, cambio ES/EN, enlace al paso de Vault y adaptación a
390 px. [Vista de reglas y resultados](../../chatbot/docs/screenshots/rar-parameters-desktop.png)
· [Vista de la traza](../../chatbot/docs/screenshots/rar-parameters-trace.png).

Referencias: [especificación RAR](https://developer.hashicorp.com/vault/ai/iam/reference/rar-type-specification),
[evaluación de restricciones](https://developer.hashicorp.com/vault/ai/iam/concepts/rar/enforcement).
