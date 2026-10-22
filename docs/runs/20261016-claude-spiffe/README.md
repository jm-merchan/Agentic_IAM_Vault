# Validación Claude · Vault SPIFFE JWT-SVID

El 16 de octubre de 2026 se retiró la demo existente y se reconstruyeron Vault, MySQL, Verify, observabilidad y Lumen antes de añadir Claude. La retirada completada inventarió **11 recursos Verify** y **10 volúmenes**; los recursos externos de los proveedores se conservaron.

La federación Claude quedó formada por:

- emisor `lumen-vault-spiffe`, con issuer `https://nondemanding-indistinguishably-claude.ngrok-free.dev/v1/verify/spiffe`;
- regla `lumen-vault-claude`, sujeto exacto `spiffe://lumen.demo/ns/verify/agent/lumen-anthropic`, audiencia `https://api.anthropic.com`, workspace `Default` y protección JTI;
- cuenta de servicio `lumen-chatbot-claude`, rol Developer;
- claves públicas de Vault en modo JWKS en línea.

Los intentos mediante discovery y URL JWKS directa quedaron registrados como `jwks_unavailable`. Con las mismas claves públicas almacenadas en línea, el capítulo [08](../../manual/08-claude-spiffe.md) pasó sus trece bloques: canje RFC 7523, listado de modelos, inferencia `CLAUDE SPIFFE OK`, rechazo de replay `jti_reused`, audiencia fija y denegaciones de base de datos y secreto administrativo.

El verificador de la aplicación confirmó:

- intercambio SPIFFE válido;
- inferencia con `claude-haiku-5-5`;
- un JWT-SVID y un token Claude nuevos por ejecución;
- ausencia de API key Anthropic estática;
- plazo de ejecución limitado.

El trace capturado `c1a11395a1435b426e3dfd70c694b50d` contiene `verify.client_credentials`, `vault.write`, `spiffe.mint_jwt_svid` y `anthropic.token_exchange`. La verificación final produjo el trace `50895623997c0e6c54bdc2c039e74e07`, con 11 spans y cuatro eventos raw de Vault correlacionados. Tempo conserva `spiffe.jwt_svid`, sus claims verificados y `anthropic.exchange.assertion`, sin incluir el access token Claude en prompts. Las **137 pruebas y dos subtests** del chatbot pasaron; `demo.sh start --provider anthropic` completó sus 21 etapas y dejó Lumen activo.

## Evidencias

- [Retirada completada](initial-remove.json) y [plan previo](initial-remove-plan.json).
- [IDs externos no secretos](federation.json).
- [Emisor con JWKS en línea](screenshots/02-issuer-inline-jwks.jpg).
- [Canjes correctos y replay rechazado](screenshots/03-authentication-events.jpg).
- [Banner Claude en Lumen](screenshots/04-lumen-claude-banner.jpg).
- [Traza Claude en Grafana](screenshots/05-grafana-claude-trace.jpg) y [atributos del JWT-SVID](screenshots/06-grafana-jwt-svid-attributes.jpg).

Los tokens, contraseñas y respuestas completas permanecen en el estado privado local. Las capturas muestran claves RSA públicas y tokens ya caducados solo cuando se abre la traza raw del laboratorio.
