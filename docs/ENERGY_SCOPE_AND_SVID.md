# Ámbito de Lumen y JWT-SVID en las trazas

La clasificación de ámbito usa el proveedor seleccionado en Lumen. Las capturas
de esta guía se renovaron el **22/10/2026**. La búsqueda pública sobre energía
está dentro del ámbito; los permisos de datos siguen dependiendo de Vault.

## Control antes del agente

El [control de ámbito](../chatbot/app/guardrails.py) se ejecuta desde `reply`, antes de construir el agente conversacional y darle herramientas. Usa una llamada independiente al mismo modelo, con salida estructurada y sin herramientas de datos o búsqueda. Clasifica energía, funciones de esta demo, conversación básica o fuera de ámbito. El historial solo ayuda a resolver referencias como «venga».

Si rechaza la consulta, el servidor devuelve una respuesta fija de redirección a energía en el idioma seleccionado en Lumen, español o inglés. No se ejecuta el agente ni se consulta Tavily/MySQL/Transit/Transform. Si falla la clasificación o no devuelve el esquema esperado, tampoco se ejecuta el agente. El prompt del agente refuerza el mismo límite y prohíbe ofrecer búsquedas, enlaces o continuaciones sobre otros temas.

Una continuación breve tras ese rechazo —«venga», «sí», «continúa», «go ahead», «continue»— se rechaza directamente, sin otra llamada al modelo ni emisión de identidad. Se reconocen las dos versiones del rechazo aunque se haya cambiado EN/ES entre mensajes. Una pregunta nueva de energía sí pasa al clasificador. Las preguntas sobre cómo afecta la lluvia a paneles solares están dentro del ámbito; preguntar el pronóstico de una ciudad queda fuera. Mezclar una petición válida con otra ajena se rechaza.

El clasificador añade una llamada al modelo por consulta normal y comparte el presupuesto de 180 segundos de la ejecución. Para clasificar con OpenAI se necesita primero el JWT-SVID y el intercambio: una petición rechazada puede tener esa operación de Vault, pero no operaciones de datos/búsqueda. Las ACL de Vault, RAR y los permisos SQL siguen siendo la frontera de autorización. La clasificación semántica es probabilística; las pruebas acreditan los casos evaluados, no una garantía para cualquier texto adversarial.

En las trazas: `guardrail.energy_scope`, con `guardrail.allowed`, `guardrail.category`, `guardrail.stage` y, para la continuación local, `guardrail.rule=blocked_followup`. La llamada de clasificación `openai.chat`, `xai.chat` o `anthropic.chat` es hija de ese span y conserva entrada/salida según el modo de captura del modelo. El idioma elegido se indica al agente para sus nuevas respuestas; no reescribe el historial ni los datos de herramientas. Las respuestas de catálogo/propuesta las construye el servidor en ese idioma después de una consulta autorizada actual. [Comprobaciones bilingües](manual/10-aplicacion.md#idioma-y-comprobaciones-bilingües).

![Meteorología y continuación rechazadas](screenshots/current/scope-denied.jpg)

## Ver el JWT-SVID

En una ejecución nueva, abrir **Ver última traza / View latest trace**, seleccionar la llamada a Vault que emite la identidad o el intercambio con el proveedor y pulsar **Ver valores sensibles / View sensitive values**. El visor muestra los valores realmente capturados y sus versiones decodificadas; EN/ES traduce los títulos, no los tokens. [Funcionamiento y retención](../chatbot/OBSERVABILITY.md#valores-de-cada-llamada).

En Tempo, los spans de emisión e intercambio conservan además estos campos explícitos:

| Paso | Campo | Qué muestra |
|---|---|---|
| `spiffe.mint_jwt_svid` | `spiffe.jwt_svid` | JWT-SVID completo emitido por Vault |
| `spiffe.mint_jwt_svid` | `spiffe.jwt_svid.decoded` | Cabecera, claims y resultado de validación local de firma |
| `openai.token_exchange` | `openai.exchange.subject_token` | El mismo JWT-SVID enviado a OpenAI |
| `anthropic.token_exchange` | `anthropic.exchange.assertion` | JWT-SVID de un solo uso enviado a Claude |

La tabla de metadatos muestra además `kid`, `jti`, issuer, audiencia, SPIFFE ID, `iat` y `exp`. La firma se valida con RS256 y JWKS de Vault antes de marcar `signature_verified=true`.

El JWT de Verify presentado **a Vault** sigue en `vault.auth.jwt`; es distinto del JWT-SVID emitido **por Vault**. El access token que devuelve OpenAI se usa en el servidor para inferencia; en modo laboratorio también se puede inspeccionar en la captura de la respuesta del intercambio. El JWT-SVID no se incorpora a los mensajes del modelo ni a las herramientas de negocio.

**Ver en Grafana** abre la misma traza de Tempo. Los campos raw dependen de `LUMEN_TRACE_VAULT_RAW=1`, ya habilitado en este laboratorio; con `0` desaparecen token y claims completos de nuevas trazas. Los datos grandes conservan indicadores de truncado. Las trazas anteriores no se reescriben: en ellas el JWT-SVID estaba dentro de `vault.http.response`, no en estos campos explícitos.

[Captura histórica: JWT-SVID y claims en el visor local](runs/20261015-energy-scope-svid/screenshots/jwt-svid-expanded.jpg)

## Verificación

La [revisión integral del 22/10](runs/20261022T140230Z-workspace-review/README.md)
registra rechazo de meteorología, continuación bloqueada y recuperación con una
petición explícita de catálogo. También conserva un falso rechazo de OpenAI a
una búsqueda de autoconsumo solar y a preguntas de arquitectura OBO de Lumen.
La política aclara ambos casos y el clasificador OpenAI usa temperatura 0;
la conversación conserva su configuración. Se repitieron 16 casos del proveedor
inicial y 48 casos con formulaciones adicionales entre los tres proveedores.
El rechazo del clasificador no acredita una denegación de Vault.

Para repetir la evaluación del proveedor inicial configurado:

```bash
# Con la demo arrancada; hace llamadas reales al proveedor activo.
bash chatbot/scripts/verify-guardrails.sh
```

El script usa una sesión técnica solo para emitir la identidad del modelo y evaluar el clasificador. No suplanta usuarios ni prueba permisos OBO humanos; el recorrido de Chrome usa el login real de `lumen-reader`.

Referencia: [OpenAI function calling y selección de herramientas](https://developers.openai.com/api/docs/guides/function-calling#tool-choice). La salida estructurada del clasificador tiene una única función de decisión; el código de aplicación aplica esa decisión antes de ejecutar Deep Agents.

![Consulta explícita del catálogo con Claude](screenshots/current/claude-catalogue.jpg)

El [ensayo adversarial del 15/10](runs/20261015-energy-scope-svid/live-evaluation.json)
y su [correlación de auditoría](runs/20261015-energy-scope-svid/live-audit-correlation.json)
son evidencia histórica. Abre **Ver última traza** en tu propia sesión para
inspeccionar una ejecución vigente.
