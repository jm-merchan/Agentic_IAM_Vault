#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
rm -f "$CHATBOT_DIR/docs/anthropic-spiffe-verification.json"
source "${VAULT_ENV_FILE:-${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}/vault/config.env}"
export VAULT_ADDR VAULT_CACERT VAULT_NAMESPACE=verify
CLAUDE_STATE="${LUMEN_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/lumen-vault-demo}/claude"
mkdir -p "$CLAUDE_STATE"
# Export only public material. After a Vault rebuild or signing-key rotation,
# Claude's inline issuer keys must be updated before this check can pass.
VAULT_TOKEN="$VAULT_TOKEN" vault read -format=json spiffe/.well-known/keys |
  jq -e '.data.keys | select(type=="array" and length>0) |
    map({kty,kid,use,alg,n,e,crv,x,y} | with_entries(select(.value!=null)))' > "$CLAUDE_STATE/issuer-keys.json"
printf 'Current Vault public keys: %s/issuer-keys.json\n' "$CLAUDE_STATE"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://127.0.0.1:4318/v1/traces}
export LUMEN_TRACE_CONTENT=${LUMEN_TRACE_CONTENT:-1}
export LUMEN_TRACE_VAULT_RAW=${LUMEN_TRACE_VAULT_RAW:-1}
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(VAULT_TOKEN="$VAULT_TOKEN" vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m | jq -er .auth.client_token)
unset VAULT_TOKEN OPENAI_ADMIN_API_KEY OPENAI_API_KEY XAI_MANAGEMENT_API_KEY
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE
cd "$CHATBOT_DIR"
if /tmp/vault-chatbot-venv/bin/python - <<'PY'
import asyncio, json, time
from datetime import datetime, UTC
from pathlib import Path
from app.anthropic_model import FederatedChatAnthropic
from app.security import load_config, Identity, Session
from app.services import Services
from app.model_config import model_config
from app.telemetry import span, trace_id

async def main():
    config = load_config()
    config['model'] = model_config(config, 'anthropic')
    if config['model'].get('provider') != 'anthropic' or config['model'].get('credential_source') != 'vault_spiffe':
        raise SystemExit('The active provider is not Claude SPIFFE.')
    services = Services(config, Identity(config))
    session = Session('verification', model_provider='anthropic', subject='verification', expires_at=time.time()+600)
    with span('lumen.verify.anthropic_spiffe'):
        tid = trace_id()
        first, deadline = await services.model_credentials(session)
        response = await asyncio.wait_for(FederatedChatAnthropic(model=first['model'], api_key=first['api_key'],
            timeout=40, max_retries=0, max_tokens=64).ainvoke('Reply only with: SPIFFE OK'), timeout=deadline-time.monotonic())
        second, _ = await services.model_credentials(session)
        checks = {'spiffe_exchange': bool(first['api_key']), 'inference': 'SPIFFE OK' in str(response.content),
                  'fresh_token_on_next_run': first['api_key'] != second['api_key'],
                  'no_static_inference_key': 'api_key' not in config['model'],
                  'deadline_bounded': 0 < deadline-time.monotonic() <= 180}
        first.pop('api_key', None); second.pop('api_key', None)
    report = {'checked_at': datetime.now(UTC).isoformat(), 'provider':'anthropic', 'integration':'SPIFFE JWT-SVID',
              'model': config['model']['model'], 'trace_id': tid, 'checks': checks, 'all_passed': all(checks.values())}
    Path('docs/anthropic-spiffe-verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if not report['all_passed']: raise SystemExit(1)
asyncio.run(main())
PY
then
  exit 0
else
  result=$?
  printf '\nThe live Claude check failed; the installation is not validated.\n' >&2
  printf 'If Vault was recreated or rotated its signing key and Claude returns HTTP 401, run: bash scripts/demo/claude-issuer.sh\n' >&2
  printf 'The sync uses the ant profile lumen-admin (or LUMEN_CLAUDE_ADMIN_PROFILE). Local public copy: %s/issuer-keys.json\n' "$CLAUDE_STATE" >&2
  printf 'To review events: https://platform.claude.com/settings/workload-identity-federation\n' >&2
  printf 'Then rerun ./demo.sh start. If it still fails, review the rule, subject, audience and permissions.\n' >&2
  exit "$result"
fi
