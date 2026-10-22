"""Update only public signing keys on the existing Claude federation issuer."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://api.anthropic.com/v1/organizations"
PUBLIC_FIELDS = {"kty", "kid", "use", "alg", "n", "e", "crv", "x", "y"}


def canonical(keys):
    return sorted((json.dumps(k, sort_keys=True) for k in keys))


def public_keys(raw):
    keys = [{k: v for k, v in key.items() if k in PUBLIC_FIELDS} for key in raw]
    if not keys or any(
        key.get("kty") != "RSA" or not all(key.get(k) for k in ("kid", "n", "e"))
        for key in keys
    ):
        raise ValueError("Vault no ha devuelto un conjunto RSA público válido.")
    if len({key["kid"] for key in keys}) != len(keys):
        raise ValueError("Vault ha devuelto identificadores de clave duplicados.")
    return keys


def save(path, data):
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def admin_token(profile):
    # Do not let the inference WIF variables or an API key override this named login.
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    if os.environ.get("ANTHROPIC_CONFIG_DIR"):
        env["ANTHROPIC_CONFIG_DIR"] = os.environ["ANTHROPIC_CONFIG_DIR"]
    try:
        result = subprocess.run(
            ["ant", "auth", "print-credentials", "--profile", profile, "--access-token"],
            env=env, capture_output=True, text=True, timeout=60, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError(
            "Falta la sesión administrativa de Claude para sincronizar las claves.\n"
            "Instala la CLI con: brew install anthropics/tap/ant\n"
            f"Inicia sesión una vez con: ant auth login --profile {profile} --scope org:admin\n"
            "Después repite ./demo.sh start. El perfil queda fuera de Vault y del chatbot."
        ) from None
    token = result.stdout.strip()
    if not token or any(c.isspace() for c in token):
        raise ValueError("La CLI de Claude no ha devuelto un token administrativo válido.")
    return token


class ClaudeAPI:
    def __init__(self, token):
        self.token = token

    def __call__(self, method, path, payload=None):
        request = Request(
            API + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + self.token,
                     "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never print response bodies, credentials, or requests.
            raise ValueError(
                f"Claude rechazó la sincronización del emisor (HTTP {exc.code}). "
                "Comprueba el perfil ant con alcance org:admin y la organización del emisor."
            ) from None
        except (URLError, TimeoutError):
            raise ValueError("No se pudo conectar con la API de Claude para sincronizar el emisor.") from None


def inspect_target(api, issuer_id, rule_id, account_id, issuer_url):
    before = api("GET", "/federation_issuers/" + issuer_id)
    rule = api("GET", "/federation_rules/" + rule_id)
    if (before.get("id") != issuer_id or before.get("archived_at")
            or before.get("issuer_url") != issuer_url
            or rule.get("archived_at") or rule.get("issuer_id") != issuer_id
            or rule.get("target", {}).get("service_account_id") != account_id
            or rule.get("oauth_scope") not in {"workspace:developer", "workspace:inference"}):
        raise ValueError("El emisor o la regla Claude no coincide con la identidad configurada. No se ha modificado.")
    return before


def sync(api, issuer_id, rule_id, account_id, issuer_url, keys):
    path = "/federation_issuers/" + issuer_id
    before = inspect_target(api, issuer_id, rule_id, account_id, issuer_url)
    desired = {"type": "inline", "keys": keys}
    current = before.get("jwks", {})
    changed = current.get("type") != "inline" or canonical(current.get("keys", [])) != canonical(keys)
    if changed:
        api("POST", path, {"jwks": desired})
    after = api("GET", path)
    invariant = ("id", "name", "issuer_url", "check_jti", "max_jwt_lifetime_seconds", "archived_at")
    if any(before.get(k) != after.get(k) for k in invariant):
        raise ValueError("La comprobación del emisor detectó cambios ajenos a sus claves públicas.")
    if (after.get("jwks", {}).get("type") != "inline"
            or canonical(after["jwks"].get("keys", [])) != canonical(keys)):
        raise ValueError("Claude no conserva las claves públicas esperadas; la instalación no está validada.")
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "issuer_id": issuer_id, "updated": changed, "key_ids": [k["kid"] for k in keys],
            "public_keys_match": True, "issuer_settings_preserved": True}


def main():
    os.umask(0o077)
    mode = os.environ.get("LUMEN_CLAUDE_SYNC_MODE", "api")
    if mode not in {"api", "console"}:
        raise ValueError("LUMEN_CLAUDE_SYNC_MODE debe ser api o console.")
    profile = os.environ.get("LUMEN_CLAUDE_ADMIN_PROFILE", "lumen-admin")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        raise ValueError("LUMEN_CLAUDE_ADMIN_PROFILE no es un nombre de perfil válido.")
    if sys.argv[1:] == ["--check-auth"]:
        if mode == "api":
            token = admin_token(profile)
            # Check access before provisioning, not just the existence of a CLI login.
            target = [os.environ.get(name) for name in (
                "ANTHROPIC_FEDERATION_ISSUER_ID", "ANTHROPIC_FEDERATION_RULE_ID",
                "ANTHROPIC_SERVICE_ACCOUNT_ID", "NGROK_DOMAIN")]
            if all(target):
                issuer_id, rule_id, account_id, domain = target
                inspect_target(ClaudeAPI(token), issuer_id, rule_id, account_id,
                               f"https://{domain}/v1/verify/spiffe")
            print("Perfil administrativo de Claude disponible.")
        else:
            print("Claude: actualización de claves por consola seleccionada; la inferencia real sigue siendo obligatoria.")
        return
    state = Path(os.environ["LUMEN_STATE_DIR"]) / "claude"
    state.mkdir(parents=True, exist_ok=True)
    report = state / "issuer-sync.json"
    report.unlink(missing_ok=True)
    names = ("ANTHROPIC_FEDERATION_ISSUER_ID", "ANTHROPIC_FEDERATION_RULE_ID",
             "ANTHROPIC_SERVICE_ACCOUNT_ID", "NGROK_DOMAIN")
    values = [os.environ.get(name, "") for name in names]
    if not all(values):
        raise ValueError("Completa " + ", ".join(names) + " en .env.")
    issuer_id, rule_id, account_id, domain = values
    if not re.fullmatch(r"fdis_[A-Za-z0-9]+", issuer_id) or not re.fullmatch(r"fdrl_[A-Za-z0-9]+", rule_id):
        raise ValueError("Los identificadores del emisor o la regla Claude no son válidos.")
    try:
        result = subprocess.run(["vault", "read", "-format=json", "spiffe/.well-known/keys"],
                                capture_output=True, text=True, timeout=30, check=True)
        keys = public_keys(json.loads(result.stdout)["data"]["keys"])
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("No se pudieron obtener las claves públicas actuales de Vault.") from None
    save(state / "issuer-keys.json", keys)
    if mode == "console":
        save(report, {"checked_at": datetime.now(timezone.utc).isoformat(),
                      "issuer_id": issuer_id, "method": "console", "verification_pending": True,
                      "key_ids": [key["kid"] for key in keys]})
        print(f"Claude: copia {state / 'issuer-keys.json'} en las claves en línea del emisor {issuer_id}.")
        print("https://platform.claude.com/settings/workload-identity-federation")
        print("Solo se ha exportado material público. El arranque exige después una federación e inferencia reales.")
        return
    api = ClaudeAPI(admin_token(profile))
    checked = sync(api, issuer_id, rule_id, account_id, f"https://{domain}/v1/verify/spiffe", keys)
    save(report, checked)
    print("Claude: claves públicas " + ("actualizadas" if checked["updated"] else "ya sincronizadas")
          + "; emisor y permisos conservados.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
