#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify
: "${NGROK_DOMAIN:?Configura NGROK_DOMAIN en .env, sin https:// ni rutas}"
[[ "$NGROK_DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]+$ ]] || fail 'NGROK_DOMAIN no es un hostname válido'
trust_domain=${SPIFFE_TRUST_DOMAIN:-lumen.demo}
[[ "$trust_domain" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+$ ]] || fail 'SPIFFE_TRUST_DOMAIN no es válido'
if ! vault secrets list -format=json | jq -e 'has("spiffe/")' >/dev/null; then
  vault secrets enable -path=spiffe spiffe >/dev/null
fi
jq -n --arg domain "$trust_domain" --arg issuer "https://$NGROK_DOMAIN/v1/verify/spiffe" \
  '{trust_domain:$domain,jwt_issuer_url:$issuer,jwt_oidc_compatibility_mode:true,jwt_signing_algorithm:"RS256",key_lifetime:"24h",bundle_refresh_hint:"1h"}' |
  vault write spiffe/config - >/dev/null
case "${LUMEN_SELECTED_PROVIDER:-openai}" in
  openai) role=lumen-openai; audience=https://api.openai.com/v1;;
  anthropic) role=lumen-anthropic; audience=https://api.anthropic.com;;
  *) fail 'SPIFFE solo se configura para openai o anthropic';;
esac
jq -n --arg sub "spiffe://$trust_domain/ns/verify/agent/$role" \
  '{template:({sub:$sub,application:"lumen",environment:"demo"}|tojson),ttl:"5m",use_jti_claim:true}' |
  vault write "spiffe/role/$role" - >/dev/null
mkdir -p "$LUMEN_STATE_DIR/openai"
vault read -format=json spiffe/.well-known/openid-configuration > "$LUMEN_STATE_DIR/openai/discovery-vault.json"
echo "SPIFFE preparado en verify/spiffe para $role ($audience); JWT-SVID con TTL 5 minutos."
