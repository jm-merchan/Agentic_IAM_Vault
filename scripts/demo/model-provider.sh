#!/usr/bin/env bash
# Sourced after .env. Explicit selection wins; auto prefers OpenAI when both exist.
select_model_provider() {
  LUMEN_SELECTED_PROVIDER=${LUMEN_PROVIDER_OVERRIDE:-${LUMEN_MODEL_PROVIDER:-auto}}
  if [ "$LUMEN_SELECTED_PROVIDER" = auto ]; then
    if [ -n "${OPENAI_ADMIN_API_KEY:-}" ]; then LUMEN_SELECTED_PROVIDER=openai
    elif [ -n "${XAI_MANAGEMENT_API_KEY:-}" ]; then LUMEN_SELECTED_PROVIDER=xai
    else fail 'Configura OPENAI_ADMIN_API_KEY o XAI_MANAGEMENT_API_KEY en .env'; fi
  fi
  case "$LUMEN_SELECTED_PROVIDER" in
    openai) [ -n "${OPENAI_ADMIN_API_KEY:-}" ] || fail 'OpenAI requiere OPENAI_ADMIN_API_KEY para el aprovisionamiento';;
    xai) [ -n "${XAI_MANAGEMENT_API_KEY:-}" ] || fail 'xAI requiere XAI_MANAGEMENT_API_KEY';;
    *) fail 'LUMEN_MODEL_PROVIDER debe ser auto, xai u openai';;
  esac
  export LUMEN_SELECTED_PROVIDER
}
