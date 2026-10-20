#!/usr/bin/env bash
set +x
set -euo pipefail
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
case "${1:-}" in
  entorno)
    [ "$(uname -s)" = Darwin ] || fail 'Este laboratorio requiere macOS/launchd.'
    for cmd in bash python3 curl jq vault kubectl helm minikube openssl uv lsof rsync plutil launchctl ngrok perl; do
      command -v "$cmd" >/dev/null || fail "Falta $cmd"
    done
    perl -MHTML::Parser -MJSON::PP -e 1
    helm upgrade --help | grep -q -- '--server-side' || fail 'Se requiere Helm 4.'
    for name in VERIFY_TENANT VERIFY_ADMIN_CLIENT_ID VERIFY_ADMIN_CLIENT_SECRET TAVILY_API_KEY ORACLE_REG_EMAIL ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD; do
      [ -n "${!name:-}" ] || fail "Completa $name en .env."
    done
    [[ "$VERIFY_TENANT" =~ ^https://[a-zA-Z0-9-]+\.verify\.ibm\.com$ ]] || fail 'VERIFY_TENANT debe ser https://<tenant>.verify.ibm.com.'
    engine=${CONTAINER_ENGINE:-podman}
    case "$engine" in podman|docker) ;; *) fail 'CONTAINER_ENGINE debe ser podman o docker.';; esac
    "$engine" info >/dev/null 2>&1 || fail "Arranca $engine antes de continuar."
    curl -fsS --connect-timeout 10 --max-time 30 "$VERIFY_TENANT/oauth2/.well-known/openid-configuration" |
      jq -e --arg issuer "$VERIFY_TENANT/oauth2" '.issuer==$issuer' >/dev/null
    echo 'Entorno listo. Los IDs WIF se comprueban al llegar a cada proveedor.'
    ;;
  spiffe-openai) export LUMEN_SELECTED_PROVIDER=openai; exec bash "$DEMO_ROOT/scripts/demo/spiffe.sh";;
  spiffe-claude) export LUMEN_SELECTED_PROVIDER=anthropic; exec bash "$DEMO_ROOT/scripts/demo/spiffe.sh";;
  openai-mapping)
    for name in OPENAI_PROJECT_ID OPENAI_SERVICE_ACCOUNT_ID OPENAI_IDENTITY_PROVIDER_ID; do
      [ -n "${!name:-}" ] || fail "Completa $name en .env según docs/manual/07-openai-spiffe.md y repite este paso."
    done
    echo 'IDs presentes. La validez del mapping se comprobará en probar-openai.'
    ;;
  claude-jwks)
    bash "$DEMO_ROOT/scripts/demo/claude-issuer.sh"
    ;;
  runtime)
    bash "$DEMO_ROOT/scripts/demo/verify-runtime.sh"
    curl -fsS --max-time 15 http://127.0.0.1:8088/health |
      jq -e '.status=="ok" and ([.models[].provider]|sort)==["anthropic","openai","xai"]' >/dev/null
    ;;
  obo)
    exec bash "$DEMO_ROOT/scripts/manual/guided-obo.sh"
    ;;
  *) fail 'Acción guiada desconocida.';;
esac
