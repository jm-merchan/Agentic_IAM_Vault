#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
command -v ngrok >/dev/null || fail 'Instala ngrok antes de preparar OpenAI'
: "${NGROK_DOMAIN:?Configura NGROK_DOMAIN}"
[[ "$NGROK_DOMAIN" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]+$ ]] || fail 'NGROK_DOMAIN no es un hostname válido'
mkdir -p "$LUMEN_STATE_DIR/ngrok"
# Free ngrok plans can serve a directory without paid Traffic Policy actions.
# This directory contains only the public discovery and JWKS documents.
public_dir="$LUMEN_STATE_DIR/ngrok/public"
publisher="$LUMEN_STATE_DIR/ngrok/publish-jwks.sh"
cp "$DEMO_ROOT/scripts/demo/publish-jwks.sh" "$publisher"
bash "$publisher" "$VAULT_ADDR" "$VAULT_CACERT" "$public_dir" "https://$NGROK_DOMAIN/v1/verify/spiffe" --once
start_managed jwks-publisher /bin/bash "$publisher" "$VAULT_ADDR" "$VAULT_CACERT" "$public_dir" "https://$NGROK_DOMAIN/v1/verify/spiffe"
ngrok_args=(--log stdout --log-format json)
if [ -n "${NGROK_AUTHTOKEN:-}" ]; then
  jq -n '{version:"3",agent:{authtoken:env.NGROK_AUTHTOKEN,web_addr:"127.0.0.1:4041"}}' > "$LUMEN_STATE_DIR/ngrok/agent.json"
  ngrok_args+=(--config "$LUMEN_STATE_DIR/ngrok/agent.json")
else
  ngrok config check >/dev/null || fail 'Configura NGROK_AUTHTOKEN o ngrok config add-authtoken'
fi
start_managed ngrok "$(command -v ngrok)" http "file://$public_dir" --url "https://$NGROK_DOMAIN" \
  --inspect=false "${ngrok_args[@]}"
mkdir -p "$LUMEN_STATE_DIR/openai"
discovery="https://$NGROK_DOMAIN/v1/verify/spiffe/.well-known/openid-configuration"
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 5 "$discovery" > "$LUMEN_STATE_DIR/openai/discovery-public.json" 2>/dev/null &&
     jq -e '.issuer and .jwks_uri' "$LUMEN_STATE_DIR/openai/discovery-public.json" >/dev/null 2>&1; then break; fi
  sleep 1
done
jq -e --arg issuer "https://$NGROK_DOMAIN/v1/verify/spiffe" '.issuer==$issuer and .jwks_uri==($issuer+"/.well-known/keys")' \
  "$LUMEN_STATE_DIR/openai/discovery-public.json" >/dev/null || fail 'Discovery público no coincide. Revisa el log privado ngrok.log'
curl -fsS --max-time 15 "https://$NGROK_DOMAIN/v1/verify/spiffe/.well-known/keys" | jq -e '.keys|length>0' >/dev/null
for path in /v1/sys/health /ui/ /v1/verify/spiffe/config /v1/verify/secrets/data/openai-admin; do
  code=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "https://$NGROK_DOMAIN$path")
  [ "$code" = 404 ] || fail "La ruta no pública $path no está bloqueada"
done
printf 'Ngrok publica únicamente discovery y JWKS: %s\n' "$discovery"
