#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
source "$DEMO_ROOT/scripts/demo/model-provider.sh"
load_inputs
select_model_provider
[ "$(uname -s)" = Darwin ] || fail 'Este lanzador usa launchd de macOS para mantener los procesos locales.'
for cmd in bash curl jq vault kubectl helm minikube openssl uv lsof rsync plutil launchctl; do
  command -v "$cmd" >/dev/null || fail "Falta $cmd"
done
helm upgrade --help | grep -q -- '--server-side' || fail 'Se requiere Helm 4 para el modo de aplicación compatible con este laboratorio.'
for name in VERIFY_TENANT VERIFY_ADMIN_CLIENT_ID VERIFY_ADMIN_CLIENT_SECRET TAVILY_API_KEY ORACLE_REG_EMAIL ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD; do
  [ -n "${!name:-}" ] || fail "Completa $name en .env"
done
if [ "$LUMEN_SELECTED_PROVIDER" = openai ]; then
  command -v ngrok >/dev/null || fail 'OpenAI SPIFFE requiere ngrok'
  [ -n "${NGROK_DOMAIN:-}" ] || fail 'Configura NGROK_DOMAIN en .env'
  if [ "${LUMEN_PREPARE_OPENAI:-0}" != 1 ]; then
    [ -n "${OPENAI_IDENTITY_PROVIDER_ID:-}" ] && [ -n "${OPENAI_SERVICE_ACCOUNT_ID:-}" ] || fail 'Ejecuta ./demo.sh prepare-openai y completa el mapping de OpenAI; consulta docs/OPENAI_SPIFFE.md'
  fi
fi
[[ "$VERIFY_TENANT" =~ ^https://[a-zA-Z0-9-]+\.verify\.ibm\.com$ ]] || fail 'VERIFY_TENANT debe ser https://<tenant>.verify.ibm.com'
case "${CONTAINER_ENGINE:-podman}" in podman|docker) ;; *) fail 'CONTAINER_ENGINE debe ser podman o docker';; esac
case "${MINIKUBE_DRIVER:-podman}" in podman|docker) ;; *) fail 'MINIKUBE_DRIVER debe ser podman o docker';; esac
command -v "${CONTAINER_ENGINE:-podman}" >/dev/null || fail 'Falta el motor de contenedores'
"${CONTAINER_ENGINE:-podman}" info >/dev/null 2>&1 || fail 'Arranca Podman/Docker antes de ejecutar la demo'
curl -fsS --connect-timeout 10 --max-time 30 "$VERIFY_TENANT/oauth2/.well-known/openid-configuration" | jq -e --arg issuer "$VERIFY_TENANT/oauth2" '.issuer==$issuer' >/dev/null
printf 'Prerrequisitos y variables completos. Proveedor: %s. No se han mostrado secretos.\n' "$LUMEN_SELECTED_PROVIDER"
