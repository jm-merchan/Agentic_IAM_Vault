#!/usr/bin/env bash
# Sourced after .env. Explicit selection wins. Claude is selected from its
# non-secret WIF resource IDs; inference never needs a static Anthropic key.
select_model_provider() {
  LUMEN_SELECTED_PROVIDER=${LUMEN_PROVIDER_OVERRIDE:-${LUMEN_MODEL_PROVIDER:-auto}}
  if [ "$LUMEN_SELECTED_PROVIDER" = auto ]; then
    if [ -n "${OPENAI_ADMIN_API_KEY:-}" ]; then LUMEN_SELECTED_PROVIDER=openai
    elif [ -n "${XAI_MANAGEMENT_API_KEY:-}" ]; then LUMEN_SELECTED_PROVIDER=xai
    elif [ -n "${ANTHROPIC_FEDERATION_RULE_ID:-}" ] && [ -n "${ANTHROPIC_ORGANIZATION_ID:-}" ] &&
         [ -n "${ANTHROPIC_SERVICE_ACCOUNT_ID:-}" ] && [ -n "${ANTHROPIC_WORKSPACE_ID:-}" ]; then
      LUMEN_SELECTED_PROVIDER=anthropic
    else fail 'Configura un proveedor: OpenAI, xAI o los cuatro IDs WIF de Claude'; fi
  fi
  case "$LUMEN_SELECTED_PROVIDER" in
    openai) [ -n "${OPENAI_ADMIN_API_KEY:-}" ] || fail 'OpenAI requiere OPENAI_ADMIN_API_KEY para el aprovisionamiento';;
    xai) [ -n "${XAI_MANAGEMENT_API_KEY:-}" ] || fail 'xAI requiere XAI_MANAGEMENT_API_KEY';;
    anthropic)
      for name in ANTHROPIC_FEDERATION_RULE_ID ANTHROPIC_ORGANIZATION_ID ANTHROPIC_SERVICE_ACCOUNT_ID ANTHROPIC_WORKSPACE_ID; do
        [ -n "${!name:-}" ] || fail "Claude requiere $name"
      done;;
    *) fail 'LUMEN_MODEL_PROVIDER debe ser auto, xai, openai o anthropic';;
  esac
  export LUMEN_SELECTED_PROVIDER
}
