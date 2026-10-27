#!/usr/bin/env bash
# All model providers use Vault-backed credentials. No static inference key is
# accepted by this helper.
provider=${1:-}
case "$provider" in openai|anthropic|xai) ;;
  *) echo 'Usage: configure-model.sh openai|anthropic|xai' >&2; exit 2;;
esac
exec bash "$(dirname "$0")/../../demo.sh" start --provider "$provider"
