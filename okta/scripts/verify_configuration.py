#!/usr/bin/env python3
"""Check persisted configuration and write only non-secret evidence."""
import json
from datetime import datetime, timezone
from pathlib import Path
from agentic_demo import vault_request
from terraform_okta import STATE_DIR, vault_read

root = Path(__file__).resolve().parents[1]
config = vault_read("okta-agentic")
checks = {}
status, response = vault_request("sys/health")
checks["vault_ready"] = status == 200 and not response["sealed"]
version = response.get("version")
license_info = response.get("license", {})
status, response = vault_request("sys/config/oauth-resource-server/okta-agentic")
profile = response.get("data", {})
checks["issuer"] = profile.get("issuer_id") == config["issuer"]
checks["jwks"] = profile.get("jwks_uri") == config["jwks_uri"] and profile.get("use_jwks") is True
checks["audience"] = profile.get("audiences") == [config["audience"]]
checks["user_claim"] = profile.get("user_claim") == "sub"
checks["rar_required_in_profile"] = profile.get("optional_authorization_details") is False

status, response = vault_request("agent-registry/registration/display-name/okta-agentic-agent")
registration = response.get("data", {})
checks["agent_registered"] = status == 200
checks["rar_optional_for_agent"] = registration.get("optional_authorization_details") is True
checks["ceiling_policy"] = registration.get("ceiling_policies") == ["okta-agentic-read"]

status, response = vault_request("identity/entity/name/okta-agentic-agent")
agent = response.get("data", {})
aliases = agent.get("aliases", [])
alias_details = [vault_request("identity/entity-alias/id/" + alias["id"])[1].get("data", {}) for alias in aliases]
checks["agent_alias"] = any(a.get("issuer") == config["issuer"] and a.get("external_id") == config["client_id"] for a in alias_details)
checks["agent_policy"] = agent.get("policies") == ["okta-agentic-read"]
status, response = vault_request("identity/entity/name/okta-agentic-human")
human = response.get("data", {})
checks["human_entity"] = status == 200 and human.get("policies") == ["okta-agentic-human"]
human_alias_ready = bool(human.get("aliases"))
subject_path = STATE_DIR / "human.tfvars.json"
if subject_path.exists():
    expected_subject = json.loads(subject_path.read_text())["human_subject"]
    human_aliases = [vault_request("identity/entity-alias/id/" + alias["id"])[1].get("data", {})
                     for alias in human.get("aliases", [])]
    checks["human_alias"] = any(alias.get("issuer") == config["issuer"] and
                                alias.get("external_id") == expected_subject for alias in human_aliases)

state = json.loads((STATE_DIR / "terraform.tfstate").read_text())
apps = {r["name"]: r["instances"][0]["attributes"] for r in state["resources"] if r["type"] == "okta_app_oauth"}
checks["client_ids"] = apps["agentic"]["client_id"] == config["client_id"] and apps["human"]["client_id"] == config["human_client_id"]
checks["client_secrets_omitted_from_state"] = all(not a.get("client_secret") and a.get("omit_secret") for a in apps.values())
checks["human_pkce_required"] = apps["human"].get("pkce_required") is True

report = {
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "vault_version": version,
    "license": license_info,
    "checks": checks,
    "human_alias_ready": human_alias_ready,
    "runtime_validation": "Run agentic_demo.py machine / login / obo; configuration checks do not prove token flows.",
}
print(json.dumps(report, indent=2))
(root / "docs/verification.json").write_text(json.dumps(report, indent=2) + "\n")
raise SystemExit(0 if all(checks.values()) else 1)
