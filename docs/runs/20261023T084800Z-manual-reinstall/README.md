# Retirada e instalación manual · 23 de octubre de 2026

[Guías](../../manual/README.md) · [Retirada y recuperación](../../manual/13-repeticion-script.md) · [Resultado](result.json)

Se retiraron los recursos operativos anteriores de Lumen y se reinstaló la demo
ejecutando por fases los bloques Bash de las guías 00–10 y las ampliaciones 14,
16 y 17. Cada bloque se extrajo con `scripts/manual/common.sh`, se ejecutó en la
sesión manual y se comprobó antes de avanzar. El registro conserva documento,
número y hash. La instalación no ejecutó `demo.sh start` ni el ciclo automático
`rehearse rebuild/install`; la retirada y las verificaciones usaron sus scripts
documentados.

## Retirada y recreación

| Recurso | Retirada verificada | Instalación nueva |
|---|---|---|
| Kubernetes | `vault`, `mysql`, `lumen-observability` ausentes | Tres namespaces con UID nuevos |
| Almacenamiento | Diez PV eliminados y diez directorios hostPath ausentes | Diez PV con UID nuevos |
| Verify | Nueve apps, un STS, cuatro grupos y tres usuarios de prueba eliminados | Los 17 recursos tienen IDs nuevos |
| xAI | Revocación de leases antes de destruir Vault | Emisión, uso, reemplazo y rechazo de clave revocada comprobados |

Evidencias: [inventario anterior](remove-plan.json), [retirada completada](remove.json),
[estado vacío](after-remove.json), [directorios eliminados](volume-recovery-result.json),
[inventario posterior de solo lectura](after-inventory.json) y
[comparación de IDs](recreated-resources.json). Los UID de namespaces están en
[before.json](before.json) y [after.json](after.json).

Se conservaron el perfil y caché de Minikube, las cuentas y federaciones externas
OpenAI/Claude, el cliente administrativo Verify, el esquema RAR compartido y el
Validador real existente. `.env` mantiene exactamente sus bytes y permisos 0600:
[comprobación](inputs-preservation.json). El estado manual anterior se archivó en
el directorio privado local; los secretos nuevos permanecen fuera del repositorio.

## Resultado de la instalación y pruebas

Vault Enterprise **2.1.2**, con tres réplicas Raft, TLS y auditoría, MySQL Enterprise
**8.3.0** con KMIP/TDE y la pila Grafana/Loki/Tempo/Alloy quedaron operativos.
OpenAI (`gpt-4.1-nano`), xAI (`grok-4.3`) y Claude (`claude-haiku-5-5`) responden
con sus identidades y credenciales de Vault. [Salud final](health.json), [pods listos](pods.json) y
[registro de bloques](installation.json).

| Verificación | Resultado | Evidencia |
|---|---|---|
| Recorridos OIDC/OBO, tres proveedores, datos protegidos, bloqueos y trazas | 137 comprobaciones y 54 trazas; todas correctas | [Workflows](workflows.json) |
| Privilegios MySQL, bootstrap y agente Tavily | 18 pruebas correctas | [Infraestructura](infrastructure-tests.json) |
| Agentes por tarea | 12 combinaciones y 36 comprobaciones agregadas correctas | [Agentes](task-agents-verification.json) |
| Espacios personales | 12 combinaciones y 120 comprobaciones correctas, incluidas denegaciones entre usuarios | [Aislamiento](personal-spaces-verification.json) |
| Parámetros RAR | Cuatro casos y 25 comparaciones correctas | [RAR](rar-parameters-verification.json) |
| Contratación CIBA | Aprobación real y nueve comprobaciones correctas | [CIBA](contracts-verification.json) |
| Configuración manual local | 46 pruebas correctas y validación de filtros de recuperación PV | [Pruebas locales](local-tests.json) |
| Documentación y sintaxis del repositorio | Sin errores | [Validación estática](static-validation.json) |

La contratación se probó tras la autorización expresa del usuario. El Validador
aprobó la solicitud `Lumen contrato 5feff551 3cf44e`; el backend creó un único
contrato, mantuvo la idempotencia y verificó dos descargas idénticas del
[PDF](contrato-verificado.pdf), con el hash registrado en el informe CIBA.
Después se [habilitó la contratación](contracts-enabled.json) y se reinició únicamente el proceso Lumen.

La inspección del entorno del proceso confirmó que no heredaba las credenciales
administrativas de aprovisionamiento: [aislamiento del runtime](runtime-isolation.json).
Los bloqueos temporales de las pruebas quedaron desactivados:
[estado final](final-state.json). La [verificación terminó](verification-state.json)
sin fases pendientes.

## Incidencias y correcciones incorporadas

1. **Podman/Minikube detenidos y Vault sellado.** Se arrancó el perfil existente
   y se desellaron las tres réplicas con sus claves anteriores antes de revocar
   los leases y retirar recursos. El [capítulo 13](../../manual/13-repeticion-script.md#si-el-clúster-estaba-detenido)
   incluye este paso previo y aclara que `remove --dry-run` no prueba la revocación.
2. **Diez PV atascados en `Released`.** El provisionador registró
   `identity annotation on PV does not match ours` tras cambiar su identidad al
   reiniciar, como describe [Minikube #16140](https://github.com/kubernetes/minikube/issues/16140).
   Se validaron el inventario, los UID, el estado `Released`, la política `Delete`,
   el nodo único y las rutas exactas de la demo. Se eliminaron los directorios y
   después los PV, sin retirar finalizers. El proceso original de retirada pudo
   terminar. El [procedimiento de recuperación](../../manual/13-repeticion-script.md#volúmenes-released-después-de-reiniciar-minikube)
   conserva estas comprobaciones; su filtro se validó también contra casos
   `Retain`, `Bound` y una ruta ajena, que fueron rechazados.
3. **Bash anidado en el instalador.** `install.sh` seleccionaba el bloque 3 de
   entorno, destinado a abrir otra terminal. En la sesión interactiva esto dejaba
   los siguientes comandos sin la función `step`. Se salió del shell hijo y se
   ejecutaron los bloques de comprobación correctos. El
   [instalador](../../../scripts/manual/install.sh) ahora selecciona los bloques
   4 y 5; el registro de instalación excluye el falso éxito del bloque 3.
4. **Ruta de Vault no exportada.** El primer `configure-rar.sh` falló intentando
   leer `/tmp/vault/config.env`. La [sesión del capítulo 00](../../manual/00-entorno.md#3-crear-una-sesión-de-trabajo-reutilizable)
   ahora exporta `VAULT_ENV_FILE` hacia el bootstrap privado. Se regeneró la
   sesión, se reconstruyeron las variables de lectura y se completó Verify.
   El [capítulo 03](../../manual/03-verify.md) explica la recuperación y se añadió
   una prueba que comprueba que un proceso hijo recibe la ruta correcta.
5. **Prerrequisitos de ampliaciones.** Los capítulos
   [16](../../manual/16-espacios-personales.md) y
   [17](../../manual/17-contratacion-ciba.md) enlazan la instalación previa del
   runtime Python. CIBA usa `guided-run.sh` para cargar `.env` y el bootstrap en
   una terminal nueva. La preparación corregida se ejecutó de nuevo sin crear
   otro cliente ni perder el Validador seleccionado.
6. **Procesos terminados al cerrar la sesión del ejecutor.** El cierre de la
   terminal de aprovisionamiento detuvo Lumen y varios auxiliares pese a `nohup`.
   Se relanzaron los mismos comandos guardados en sesiones independientes, con
   logs privados, y se comprobaron de nuevo la salud, los puertos, las JWKS
   públicas y la ausencia de credenciales administrativas en Lumen.
   [Registro de recuperación](process-recovery.json). El capítulo 13 explica
   esta diferencia entre SIGHUP y la limpieza del árbol de procesos del ejecutor.

Claude ya tenía `LUMEN_CLAUDE_SYNC_MODE=console`. Se actualizaron únicamente las
JWKS públicas del emisor existente mediante Chrome y se comparó el JSON completo
guardado con el del nuevo Vault. Se conservaron la regla, permisos, protección
JTI y duración máxima de una hora. [Evidencia de sincronización](claude-console-sync.json)
y [claves públicas](claude-jwks.json). Las pruebas posteriores verificaron emisión,
inferencia, rechazo de replay y restricciones de audiencia. No se intentó la API
administrativa Claude en esta ejecución.

## Alcance de las evidencias

Las comprobaciones funcionales usan servicios reales y cuentas de laboratorio;
las 46 pruebas de configuración son locales. La validación estática revisa
sintaxis, enlaces, notebooks y la integridad de las capturas existentes. No se
repitió toda la suite de aplicación ni se generó una nueva revisión visual completa.

Chrome se usó para las JWKS y para comprobar que Lumen mostraba el catálogo y
permitía seleccionar Claude. No se completó el login desde Chrome en esta sesión.
La descarga y el hash del PDF están acreditados en el backend; no se verificaron
el archivo descargado por el navegador ni su representación visual.

Los logs privados conservan los intentos fallidos y su recuperación. El registro
de bloques recoge ejecuciones correctas, incluidas repeticiones de lecturas y
pasos idempotentes; su contador no representa un número de pasos únicos.

Accesos locales al finalizar: [Lumen](http://localhost:8088),
[Grafana](http://localhost:3000/d/lumen-iam) y
[Vault](https://127.0.0.1:8443/ui). Los procesos manuales y port-forwards siguen
activos; dependen de que Podman y Minikube permanezcan en ejecución.
