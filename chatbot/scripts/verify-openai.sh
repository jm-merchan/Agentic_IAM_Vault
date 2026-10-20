#!/usr/bin/env bash
# Bash orchestration; the same Python runtime used by the app exercises its flow.
set +x
set -euo pipefail
umask 077
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
rm -f "$CHATBOT_DIR/docs/openai-spiffe-verification.json"
source "${VAULT_ENV_FILE:-/tmp/vault/config.env}"
export VAULT_ADDR VAULT_CACERT VAULT_NAMESPACE=verify
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://127.0.0.1:4318/v1/traces}
export LUMEN_TRACE_CONTENT=${LUMEN_TRACE_CONTENT:-1}
export LUMEN_TRACE_VAULT_RAW=${LUMEN_TRACE_VAULT_RAW:-1}
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(VAULT_TOKEN="$VAULT_TOKEN" vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m | jq -er .auth.client_token)
unset VAULT_TOKEN OPENAI_ADMIN_API_KEY OPENAI_API_KEY XAI_MANAGEMENT_API_KEY
cd "$CHATBOT_DIR"
/tmp/vault-chatbot-venv/bin/python - <<'PY'
import asyncio, json, time
from datetime import datetime, UTC
from pathlib import Path
from langchain_openai import ChatOpenAI
from app.security import load_config, Identity, Session
from app.services import Services
from app.model_config import model_config
from app.telemetry import span, trace_id

async def main():
    config = load_config()
    config['model'] = model_config(config, 'openai')
    if config['model'].get('credential_source') != 'vault_spiffe':
        raise SystemExit('El proveedor activo no es OpenAI SPIFFE.')
    services = Services(config, Identity(config))
    session = Session('verification', model_provider='openai', subject='verification', expires_at=time.time()+600)
    with span('lumen.verify.openai_spiffe'):
        tid = trace_id()
        first, deadline = await services.model_credentials(session)
        response = await asyncio.wait_for(ChatOpenAI(model=first['model'], api_key=first['api_key'],
            timeout=40, max_retries=0).ainvoke('Reply only with: SPIFFE OK'), timeout=deadline-time.monotonic())
        second, _ = await services.model_credentials(session)
        checks = {'spiffe_exchange': bool(first['api_key']), 'inference': 'SPIFFE OK' in str(response.content),
                  'fresh_token_on_next_run': first['api_key'] != second['api_key'],
                  'no_static_inference_key': 'api_key' not in config['model'],
                  'deadline_bounded': 0 < deadline-time.monotonic() <= 180}
        first.pop('api_key', None); second.pop('api_key', None)
    report = {'checked_at': datetime.now(UTC).isoformat(), 'provider':'openai', 'integration':'SPIFFE JWT-SVID',
              'model': config['model']['model'], 'trace_id': tid, 'checks': checks, 'all_passed': all(checks.values())}
    Path('docs/openai-spiffe-verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if not report['all_passed']: raise SystemExit(1)
asyncio.run(main())
PY
