#!/usr/bin/env python3
"""Exercise Okta -> Vault without logging or writing bearer tokens to local files."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt
from terraform_okta import STATE_DIR, vault_config, vault_read


def request_json(url, data=None, headers=None, context=None, method=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, context=context, timeout=25) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def vault_request(path, payload=None, token=None, method=None):
    config = vault_config()
    headers = {"X-Vault-Token": config["VAULT_TOKEN"] if token is None else token}
    if config.get("VAULT_NAMESPACE"):
        headers["X-Vault-Namespace"] = config["VAULT_NAMESPACE"]
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return request_json(
        config["VAULT_ADDR"].rstrip("/") + "/v1/" + path,
        None if payload is None else json.dumps(payload).encode(), headers,
        ssl.create_default_context(cafile=config.get("VAULT_CACERT")), method,
    )


def save_session(key, value):
    status, result = vault_request("secrets/data/okta-agentic-session")
    if status == 404:
        values, version = {}, 0
    elif status == 200:
        values, version = result["data"]["data"], result["data"]["metadata"]["version"]
    else:
        raise RuntimeError("Cannot read session metadata: HTTP " + str(status))
    values[key] = value
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    status, _ = vault_request("secrets/data/okta-agentic-session", {
        "data": values, "options": {"cas": version},
    })
    if status not in (200, 204):
        raise RuntimeError("Cannot save session: HTTP " + str(status))


def validate(token, config):
    key = jwt.PyJWKClient(config["jwks_uri"]).get_signing_key_from_jwt(token)
    return jwt.decode(token, key.key, algorithms=["RS256"],
                      issuer=config["issuer"], audience=config["audience"],
                      options={"require": ["exp", "iat", "iss", "sub", "aud", "jti"]})


def token_request(config, payload, human=False):
    prefix = "human_" if human else ""
    credentials = config[prefix + "client_id"] + ":" + config[prefix + "client_secret"]
    status, body = request_json(config["issuer"] + "/v1/token",
        urllib.parse.urlencode(payload).encode(), {
            "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        })
    if status != 200:
        # Print only OAuth error fields, never an echoed request or token.
        raise RuntimeError(f"Okta HTTP {status}: {body.get('error')}: {body.get('error_description')}")
    claims = validate(body["access_token"], config)
    print(json.dumps({"signature_verified": True, **{
        key: claims.get(key) for key in ("iss", "aud", "sub", "act", "scp", "exp")
    }}, indent=2))
    return body, claims


def machine(config):
    body, claims = token_request(config, {"grant_type": "client_credentials", "scope": config["scope"]})
    if claims["sub"] != config["client_id"] or claims.get("act"):
        raise RuntimeError("Unexpected autonomous agent identity")
    save_session("machine", body)
    return probe(body["access_token"], "machine")


def login(config):
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # OAuth codes in the request URI must not enter logs.

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path != "/callback" or params.get("state", [None])[0] != state:
                self.send_error(400, "Invalid callback state")
                return
            result.update({key: values[0] for key, values in params.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b'<html><head><script>history.replaceState({},"","/callback")</script></head><body><h1>Callback received</h1><p>Return to the notebook to check the exchange result.</p></body></html>')

    server = HTTPServer(("127.0.0.1", 9876), Callback)
    server.timeout = 1
    url = config["issuer"] + "/v1/authorize?" + urllib.parse.urlencode({
        "client_id": config["human_client_id"], "response_type": "code",
        "scope": "openid profile email offline_access " + config["scope"],
        "redirect_uri": config["redirect_uri"], "state": state,
        "code_challenge_method": "S256", "code_challenge": challenge,
    })
    print("Open this URL in Chrome and complete the sign-in:\n" + url, flush=True)
    deadline = time.monotonic() + 600
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in result:
        raise RuntimeError("Login incomplete: " + result.get("error", "callback timed out"))
    body, claims = token_request(config, {
        "grant_type": "authorization_code", "code": result["code"],
        "redirect_uri": config["redirect_uri"], "code_verifier": verifier,
    }, human=True)
    save_session("human", body)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = STATE_DIR / "human.tfvars.json"
    target.write_text(json.dumps({"human_subject": claims["sub"]}) + "\n")
    target.chmod(0o600)
    print("Human subject verified and saved for Terraform; tokens stored only in Vault.")


def obo(config):
    human = vault_read("okta-agentic-session")["human"]["access_token"]
    subject = validate(human, config)["sub"]
    body, claims = token_request(config, {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "subject_token": human, "scope": config["scope"], "audience": config["audience"],
    })
    if claims["sub"] != subject or claims.get("act", {}).get("sub") != config["client_id"]:
        raise RuntimeError("OBO not verified: missing or unexpected sub/act.sub; do not treat token as delegation.")
    save_session("obo", body)
    return probe(body["access_token"], "obo")


def probe(token, flow):
    cases = [
        ("read_shared", "secrets/data/agentic-demo/shared", None, 200),
        ("write_shared", "secrets/data/agentic-demo/shared", {"data": {"message": "Must be denied"}}, 403),
        ("read_human_only", "secrets/data/agentic-demo/human-only", None, 403),
        ("read_bootstrap", "secrets/data/okta", None, 403),
    ]
    results = []
    for name, path, data, expected in cases:
        status, body = vault_request(path, payload=data, token=token)
        record = {"flow": flow, "test": name, "http_status": status, "expected": expected, "passed": status == expected}
        if status != expected and status >= 400:
            record["errors"] = body.get("errors", [])
        results.append(record)
        print(json.dumps(record))
    save_session(flow + "_results", results)
    return all(row["passed"] for row in results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["machine", "login", "obo", "verify"])
    args = parser.parse_args()
    os.umask(0o077)
    config = vault_read("okta-agentic")
    if args.command == "login":
        login(config)
    elif args.command == "machine":
        return 0 if machine(config) else 1
    elif args.command == "obo":
        return 0 if obo(config) else 1
    else:
        session = vault_read("okta-agentic-session")
        ok = True
        for flow in ("machine", "obo"):
            token = session[flow]["access_token"]
            validate(token, config)
            ok = probe(token, flow) and ok
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, jwt.PyJWTError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
