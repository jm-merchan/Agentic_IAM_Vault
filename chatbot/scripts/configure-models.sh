#!/usr/bin/env bash
# Publish all three preconfigured profiles atomically. This does not create
# identities or copy inference secrets; existing Vault agents are required.
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
source "$DEMO_ROOT/verify/scripts/common.sh"
for name in NGROK_DOMAIN OPENAI_IDENTITY_PROVIDER_ID OPENAI_SERVICE_ACCOUNT_ID ANTHROPIC_FEDERATION_RULE_ID ANTHROPIC_ORGANIZATION_ID ANTHROPIC_SERVICE_ACCOUNT_ID ANTHROPIC_WORKSPACE_ID; do
  [ -n "${!name:-}" ] || fail "Set $name to preconfigure all three providers"
done
for provider in openai xai anthropic; do
  kv_read "chatbot/$provider" | jq -e '.client_id and .client_secret' >/dev/null
done
default=${LUMEN_PROVIDER_OVERRIDE:-${LUMEN_MODEL_PROVIDER:-auto}}
case "$default" in auto|all) default=openai;; openai|xai|anthropic) ;; *) fail 'Invalid initial provider';; esac
jq -n --arg default "$default" \
  --arg openai "${LUMEN_OPENAI_MODEL:-gpt-5.6-luna}" --arg xai "${LUMEN_XAI_MODEL:-grok-4.3}" \
  --arg anthropic "${LUMEN_ANTHROPIC_MODEL:-claude-haiku-5-5}" \
  --arg idp "$OPENAI_IDENTITY_PROVIDER_ID" --arg openai_account "$OPENAI_SERVICE_ACCOUNT_ID" \
  --arg rule "$ANTHROPIC_FEDERATION_RULE_ID" --arg org "$ANTHROPIC_ORGANIZATION_ID" \
  --arg account "$ANTHROPIC_SERVICE_ACCOUNT_ID" --arg workspace "$ANTHROPIC_WORKSPACE_ID" \
  --arg issuer "https://$NGROK_DOMAIN/v1/verify/spiffe" --arg trust "${SPIFFE_TRUST_DOMAIN:-lumen.demo}" '
  {openai:{provider:"openai",model:$openai,credential_source:"vault_spiffe",
    credential_path:"spiffe/role/lumen-openai/mintjwt",auth_flow:"spiffe_jwt_svid",
    issuer:$issuer,spiffe_id:("spiffe://"+$trust+"/ns/verify/agent/lumen-openai"),
    audience:"https://api.openai.com/v1",identity_provider_id:$idp,service_account_id:$openai_account},
   xai:{provider:"xai",model:$xai,credential_source:"vault_dynamic",credential_path:"xai/creds/lumen",
    credential_ttl:300,auth_flow:"client_credentials"},
   anthropic:{provider:"anthropic",model:$anthropic,credential_source:"vault_spiffe",
    credential_path:"spiffe/role/lumen-anthropic/mintjwt",auth_flow:"spiffe_jwt_svid",
    issuer:$issuer,spiffe_id:("spiffe://"+$trust+"/ns/verify/agent/lumen-anthropic"),
    audience:"https://api.anthropic.com",federation_rule_id:$rule,organization_id:$org,
    service_account_id:$account,workspace_id:$workspace}} as $profiles |
  $profiles[$default] + {providers:$profiles}' | kv_write chatbot/model
echo 'OpenAI, xAI and Claude preconfigured; select one from the Lumen banner.'
