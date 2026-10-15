#!/usr/bin/env python3
"""Run Terraform with the Okta bootstrap credentials held in Vault, never in state."""
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path.home() / ".local/share/okta-vault-agentic"


def vault_config():
    path = Path(os.environ.get("VAULT_CONFIG_FILE", "/tmp/vault/config.env"))
    config = {}
    for line in path.read_text().splitlines():
        line = line.strip().removeprefix("export ")
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values = shlex.split(value)
            config[key.strip()] = values[0] if values else ""
    for key in ("VAULT_ADDR", "VAULT_TOKEN", "VAULT_CACERT", "VAULT_NAMESPACE"):
        if key in os.environ:
            config[key] = os.environ[key]
    return config


def vault_read(path):
    config = vault_config()
    headers = {"X-Vault-Token": config["VAULT_TOKEN"]}
    if config.get("VAULT_NAMESPACE"):
        headers["X-Vault-Namespace"] = config["VAULT_NAMESPACE"]
    request = urllib.request.Request(
        config["VAULT_ADDR"].rstrip("/") + "/v1/secrets/data/" + path,
        headers=headers,
    )
    context = ssl.create_default_context(cafile=config.get("VAULT_CACERT"))
    with urllib.request.urlopen(request, context=context, timeout=20) as response:
        return json.load(response)["data"]["data"]


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("Usage: python3 scripts/terraform_okta.py <terraform command> [arguments]")
    os.umask(0o077)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("OKTA_", "TF_LOG", "TF_CLI_ARGS"))}
    env["TF_DATA_DIR"] = str(STATE_DIR / "data")
    env.update({key: value for key, value in vault_config().items() if key.startswith("VAULT_")})
    credentials = vault_read("okta")
    for field, name in {
        "org_name": "OKTA_ORG_NAME", "base_url": "OKTA_BASE_URL",
        "client_id": "OKTA_API_CLIENT_ID", "private_key_id": "OKTA_API_PRIVATE_KEY_ID",
        "private_key": "OKTA_API_PRIVATE_KEY", "scopes": "OKTA_API_SCOPES",
    }.items():
        env[name] = credentials[field]
    if args[0] == "init":
        args.append("-backend-config=path=" + str(STATE_DIR / "terraform.tfstate"))
    subject_file = STATE_DIR / "human.tfvars.json"
    if subject_file.exists():
        env["TF_VAR_human_subject"] = json.loads(subject_file.read_text())["human_subject"]
    result = subprocess.run(["terraform", "-chdir=" + str(ROOT / "terraform/okta"), *args], env=env)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
