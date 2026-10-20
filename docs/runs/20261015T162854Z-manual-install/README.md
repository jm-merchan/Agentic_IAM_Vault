# Reconstrucción siguiendo las guías manuales · 15 de octubre de 2026

[Guías](../../manual/README.md) · [Validación más reciente](../../manual/VALIDACION.md)

**Evidencia histórica.** Este despliegue se retiró. Sus trazas ya no están en el Tempo actual. El [ciclo completo del 16/10](../20261016T064722Z-manual-script/README.md) es la validación vigente; las limitaciones y los accesos descritos debajo corresponden al ensayo del 15/10.

La instalación se ejecutó mediante los bloques Markdown, copiados a archivos privados para conservar exactamente el Bash utilizado. No se ejecutaron notebooks ni scripts de aprovisionamiento. `demo.sh remove` se utilizó únicamente para la retirada revisada y autorizada.

## Evidencias

- [Plan de retirada](remove-plan.json) y [retirada completada](remove.json).
- [Namespaces anteriores](before.json) y [nuevos](after.json): los UID cambian.
- [Identidades de los agentes de esta ejecución](agents.json). Los IDs se obtienen del Vault nuevo.
- [Comprobaciones funcionales](verification.json): 33 verificaciones completadas, todas correctas. Incluye una lista explícita de recorridos pendientes por indisponibilidad del navegador.
- [Inferencia y revocación xAI](xai.json), [caducidad de una clave de 60 s](xai-expiry.json).
- [Token exchange e inferencia OpenAI](openai.json), [inventario sin claves API estáticas](openai-static-keys.json).

El lector inició sesión por OIDC/PKCE y completó las nueve comprobaciones de permisos en la interfaz. Captura de esta instalación:

![Lector: permisos SQL, Transit y Transform](screenshots/reader-permissions.png)

Traza de esa acción: `e8088316f06a99fd6371054797866a7e`; 29 spans, nueve IDs de petición de Vault y 36 eventos audit (request/response, HMAC/raw). Para consultarla, seguir [08 · correlación](../../manual/08-observabilidad.md). Los eventos completos contienen valores del laboratorio y se conservan en los servicios locales, no en este informe.

Lector y gestor completaron además los comandos de OBO, SQL y protección de datos. El gestor pudo escribir en una transacción revertida y cifrar/tokenizar; no pudo recuperar datos sensibles. Las pruebas pendientes no se consideran aprobadas por inferencia a partir de las políticas.

## Accesos al despliegue manual

- [Lumen](http://localhost:8088): OpenAI `gpt-4.1-mini`, SPIFFE JWT-SVID.
- [Vault](https://127.0.0.1:8443/ui/): credencial administrativa en `~/.local/state/lumen-vault-demo/vault/config.env`, namespace `verify`.
- [Grafana](http://localhost:3000/d/lumen-iam): `lumen-admin`, contraseña en `secrets/chatbot/observability` del namespace `verify`.

Los procesos manuales se mantienen en terminales: Lumen, forwards y ngrok/publicador JWKS. Para detenerlos o volver al lanzador, cerrar primero esos procesos según [09](../../manual/09-aplicacion.md). `demo.sh stop` administra sus propios servicios; no sustituye el cierre de todas las terminales manuales.
