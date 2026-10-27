#!/usr/bin/env bash
set +x
set -euo pipefail
source "$(dirname "$0")/../../scripts/demo/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify
export LUMEN_ROOT="$DEMO_ROOT" MANUAL="$LUMEN_STATE_DIR/manual"
export MANUAL_RUN="$MANUAL/guided/reports"
mkdir -p "$MANUAL_RUN"
rm -f "$MANUAL_RUN/obo.json"
for role in reader writer supervisor; do
  LUMEN_GUIDED=1 bash "$DEMO_ROOT/scripts/manual/oidc-login.sh" "$role"
done
export CHATBOT_BOOTSTRAP_TOKEN
CHATBOT_BOOTSTRAP_TOKEN=$(vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m | jq -er .auth.client_token)
unset VAULT_TOKEN VERIFY_ADMIN_CLIENT_SECRET OPENAI_ADMIN_API_KEY OPENAI_API_KEY XAI_MANAGEMENT_API_KEY
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN TAVILY_API_KEY ORACLE_REG_PASSWORD VAULT_LICENSE MYSQL_ROOT_PASSWORD
unset LUMEN_READER_PASSWORD LUMEN_WRITER_PASSWORD LUMEN_SUPERVISOR_PASSWORD
export PYTHONPATH="$DEMO_ROOT/chatbot"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
/tmp/vault-chatbot-venv/bin/python - <<'PY'
import asyncio, json, os
from datetime import datetime, timezone
from pathlib import Path
from app.security import load_config, Identity, Session
from app.services import Services
from app.telemetry import span, trace_id, records_for

async def main():
    config = load_config()
    identity = Identity(config)
    services = Services(config, identity)
    private = Path(os.environ["MANUAL"])
    checks = []
    for role in ("reader", "writer", "supervisor"):
        tokens = json.loads((private / f"human-{role}.json").read_text())
        claims = identity.validate(tokens["access_token"], config["oidc"]["client_id"])
        id_claims = identity.validate(tokens["id_token"], config["oidc"]["client_id"])
        assert claims["sub"] == id_claims["sub"], "OIDC subject mismatch"
        assert id_claims["nonce"] == (private / f"login-{role}/nonce").read_text(), "OIDC nonce mismatch"
        assert claims["may_act"]["client_id"] == config["oidc"]["client_id"], "Missing may_act"
        session = Session("guided-" + role, subject=claims["sub"], name=role,
                          groups=claims["groups"], access_token=tokens["access_token"],
                          expires_at=min(claims["exp"], id_claims["exp"]))
        with span("verification.guided_obo", **{"user.role": role}):
            await services.permission_probe(session)
            probe = next(r["attributes"] for r in records_for({trace_id()})
                         if r["name"] == "permissions.probe")
            passed = (probe.get("probe.check_count") == 9
                      and probe.get("probe.matches_expected") is True)
        checks.append({"role": role, "passed": passed})
        print(f"{role}: {'9/9 OK' if passed else 'FALLO'}", flush=True)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
              "all_passed": all(check["passed"] for check in checks)}
    (Path(os.environ["MANUAL_RUN"]) / "obo.json").write_text(json.dumps(report, indent=2) + "\n")
    if not report["all_passed"]:
        raise SystemExit(1)

asyncio.run(main())
PY
