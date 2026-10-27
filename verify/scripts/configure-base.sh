#!/usr/bin/env bash
# Lumen base: no previous human login or vault-authn-entry instance required.
source "$(dirname "$0")/common.sh"
admin_login
source "$VERIFY_DIR/scripts/rar-common.sh"
configure_rar
# Match the client's 15-second JWT leeway. Zero rejects freshly issued tokens
# when the IdP clock is a fraction of a second ahead of the VM after resume.
jq -n --arg issuer "$TENANT/oauth2" '{issuer_id:$issuer,jwks_uri:($issuer+"/jwks"),use_jwks:true,user_claim:"sub",actor_claim:"actor-token.sub",supported_algorithms:["RS256"],jwt_type:"access_token",clock_skew_leeway:15,no_default_policy:true,optional_authorization_details:false}' | vault write sys/config/oauth-resource-server/verify - >/dev/null
echo 'RAR and Vault OAuth profile ready; no prior human session required.'
