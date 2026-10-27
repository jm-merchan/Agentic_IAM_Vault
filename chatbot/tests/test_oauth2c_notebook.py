"""Run the published cells with real oauth2c and a local synthetic OAuth server."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "10_OAuth2c_Verify_Vault.ipynb"
OAUTH2C = shutil.which("oauth2c")
CELLS = {
    c["id"]: "".join(c["source"]).removeprefix("%%bash\n")
    for c in json.loads(NOTEBOOK.read_text())["cells"] if c["cell_type"] == "code"
}


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def jwt(claims):
    # Deliberately synthetic: the helper decodes; actual Vault verifies signatures.
    return ".".join([b64(b'{"alg":"RS256"}'), b64(json.dumps(claims).encode()), "synthetic"])


def claims(token):
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))


class OAuthServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), OAuthHandler)
        self.tenant = f"http://127.0.0.1:{self.server_port}"
        self.calls = []
        self.authorizations = {}
        self.fail_tokens = False
        self.refresh_enabled = False
        self.app = {
            "name": "vault-chatbot-oidc", "description": "preserve-me",
            "providers": {"oidc": {"properties": {
                "redirectUris": ["http://localhost:8088/auth/callback"],
                "grantTypes": {"authorizationCode": "true", "ropc": "false"},
                "generateRefreshToken": "false",
            }}},
        }

    def token(self, subject, **extra):
        return jwt({"iss": self.tenant + "/oauth2", "sub": subject,
                    "exp": int(time.time()) + 600, **extra})


class OAuthHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, body, status=200):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/oauth2/.well-known/openid-configuration":
            issuer = self.server.tenant + "/oauth2"
            self.reply({
                "issuer": issuer, "authorization_endpoint": issuer + "/authorize",
                "token_endpoint": issuer + "/token", "response_types_supported": ["code"],
                "grant_types_supported": ["client_credentials", "authorization_code",
                    "urn:ietf:params:oauth:grant-type:token-exchange", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                "code_challenge_methods_supported": ["S256"],
            })
        elif path == "/oauth2/authorize":
            q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            assert q["response_type"] == "code"
            assert q["code_challenge_method"] == "S256"
            assert q["redirect_uri"] in self.server.app["providers"]["oidc"]["properties"]["redirectUris"]
            self.server.authorizations["synthetic-code"] = q
            self.send_response(302)
            self.send_header("Location", q["redirect_uri"] + "?" + urlencode({
                "code": "synthetic-code", "state": q["state"],
            }))
            self.end_headers()
        elif path == "/v1.0/applications/fixture-app":
            assert self.headers["Authorization"] == "Bearer synthetic-admin-token"
            self.server.calls.append(("GET", path))
            self.reply(self.server.app)
        else:
            self.reply({"error": "unexpected_path"}, 404)

    def do_PUT(self):
        assert self.path == "/v1.0/applications/fixture-app"
        assert self.headers["Authorization"] == "Bearer synthetic-admin-token"
        self.server.app = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append(("PUT", self.path))
        self.reply(self.server.app)

    def do_POST(self):
        assert self.path == "/oauth2/token"
        data = {k: v[0] for k, v in parse_qs(
            self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        auth = self.headers["Authorization"]
        assert auth.startswith("Basic ")
        client, secret = base64.b64decode(auth[6:]).decode().split(":", 1)
        assert secret == "synthetic-secret-" + client
        assert "client_secret" not in data  # Basic, not client_secret_post
        self.server.calls.append(("TOKEN", client, data))
        if self.server.fail_tokens:
            self.reply({"error": "invalid_client"}, 401)
            return
        grant = data["grant_type"]
        extra = {}
        if grant == "client_credentials":
            if client == "admin":
                self.reply({"access_token": "synthetic-admin-token", "token_type": "Bearer"})
                return
            assert client in ("oidc", "research")
            assert data["scope"] == "openid profile email"
            token = self.server.token(client)
        elif grant == "authorization_code":
            assert client == "oidc"
            q = self.server.authorizations[data["code"]]
            assert data["redirect_uri"] == q["redirect_uri"]
            assert b64(hashlib.sha256(data["code_verifier"].encode()).digest()) == q["code_challenge"]
            token = self.server.token("human", groups=["readers"], may_act={"client_id": "oidc"})
            if self.server.refresh_enabled:
                extra["refresh_token"] = "synthetic-refresh"
        elif grant == "urn:ietf:params:oauth:grant-type:token-exchange":
            assert client == "sts"
            for key in ("subject_token_type", "actor_token_type", "requested_token_type"):
                assert data[key] == "urn:ietf:params:oauth:token-type:access_token"
            human, actor = claims(data["subject_token"]), claims(data["actor_token"])
            assert human["sub"] == "human" and actor["sub"] == "oidc"
            assert human["may_act"]["client_id"] == actor["sub"]
            rar = json.loads(data["authorization_details"])
            assert rar == [{"type": "vault:path_access", "path": "database/creds/chatbot-readonly",
                            "capabilities": ["read"]}]
            token = self.server.token(human["sub"], **{
                "actor-token": {"sub": actor["sub"]}, "authorization_details": rar,
                "groups": human["groups"],
            })
        elif grant == "refresh_token":
            assert client == "oidc" and data["refresh_token"] == "synthetic-refresh"
            token = self.server.token("human", groups=["readers"], may_act={"client_id": "oidc"})
        else:
            raise AssertionError(grant)
        self.reply({"access_token": token, "token_type": "Bearer", "expires_in": 600, **extra})


@pytest.fixture
def lab(tmp_path):
    if not OAUTH2C:
        pytest.skip("Install oauth2c to exercise the actual CLI against the local fixture")
    server = OAuthServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = tmp_path / "repo with spaces"
    helper_dir = root / "verify/scripts"
    helper_dir.mkdir(parents=True)
    shutil.copy(ROOT / "verify/scripts/oauth2c-common.sh", helper_dir)
    (root / "scripts/demo").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/demo/env-file.sh", root / "scripts/demo")
    state = tmp_path / "private state"
    (state / "vault").mkdir(parents=True)
    (state / "vault/config.env").write_text(
        "VAULT_ADDR=https://vault.invalid\nVAULT_TOKEN=synthetic-bootstrap\nVAULT_CACERT=fixture-ca\n")
    (root / ".env").write_text(f"VERIFY_TENANT={server.tenant}\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "vault").write_text("""#!/usr/bin/env python3
import base64, json, os, sys
args = sys.argv[1:]
assert os.environ['VAULT_NAMESPACE'] == 'verify'
if args[:2] == ['kv', 'get']:
    path = args[-1]
    if path == os.environ.get('FAIL_CREDENTIAL'):
        raise SystemExit('Synthetic Vault read failure')
    name = 'admin' if path == 'verify-admin' else path.rsplit('/',1)[-1]
    assert name in ['admin','oidc','sts','research']
    assert os.environ['VAULT_TOKEN'] == 'synthetic-bootstrap'
    print(json.dumps({'data': {'data': {
        'application_id': 'fixture-app', 'client_id': name,
        'client_secret': 'synthetic-secret-' + name,
    }}}))
elif args[:2] == ['read', '-format=json']:
    token = os.environ['VAULT_TOKEN']
    c = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
    assert c['sub'] == 'human' and c['actor-token']['sub'] == 'oidc'
    if args[-1] == 'database/creds/chatbot-readonly':
        print(json.dumps({'lease_id':'database/creds/chatbot-readonly/synthetic',
            'lease_duration':600, 'renewable':True,
            'data':{'username':'synthetic-user','password':'synthetic-password'}}))
    else:
        message = os.environ.get('VAULT_DENIED_ERROR', 'Code: 403. Errors: permission denied')
        print(message, file=sys.stderr)
        raise SystemExit(2)
else:
    raise SystemExit('Unexpected Vault invocation')
""")
    (bindir / "vault").chmod(0o700)
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("VAULT_", "VERIFY_", "LUMEN_", "OAUTH2C_", "DEMO_", "FAIL_", "PYTHON"))}
    env.update(PATH=str(bindir) + os.pathsep + env["PATH"], LUMEN_STATE_DIR=str(state))
    fixture = type("Lab", (), {})()
    fixture.root, fixture.state, fixture.env, fixture.server = root, state, env, server
    fixture.private = state / "oauth2c"
    try:
        yield fixture
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def run(lab, cell, success=True):
    result = subprocess.run(["/bin/bash", "-c", CELLS.get(cell, cell)], env=lab.env,
                            cwd=lab.root, text=True, capture_output=True, timeout=20)
    if success:
        assert result.returncode == 0, result.stderr + result.stdout
    else:
        assert result.returncode != 0
    return result


def login(lab):
    # Exercise the exact cell, observing the URL just as IPython streams stderr.
    err = lab.root / "login.stderr"
    out = lab.root / "login.stdout"
    with out.open("w") as stdout, err.open("w") as stderr:
        process = subprocess.Popen(["/bin/bash", "-c", CELLS["human"]], cwd=lab.root,
                                   env=lab.env, stdout=stdout, stderr=stderr)
    try:
        deadline = time.monotonic() + 8
        url = None
        while time.monotonic() < deadline and process.poll() is None:
            url = next((line for line in err.read_text().splitlines()
                        if line.startswith(lab.server.tenant + "/oauth2/authorize?")), None)
            if url:
                break
            time.sleep(0.05)
        assert url, err.read_text()
        # oauth2c logs the URL just before starting its callback listener.
        for attempt in range(20):
            try:
                with urlopen(url, timeout=2) as response:
                    assert response.status == 200
                break
            except URLError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
        process.wait(timeout=8)
        assert process.returncode == 0, err.read_text() + out.read_text()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_notebook_structure_and_shell_syntax():
    nb = json.loads(NOTEBOOK.read_text())
    assert nb["nbformat"] == 4
    assert len({c["id"] for c in nb["cells"]}) == len(nb["cells"])
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            source = "".join(cell["source"])
            assert source.startswith("%%bash\n")
            result = subprocess.run(["/bin/bash", "-n"], input=source[7:],
                                    text=True, capture_output=True)
            assert result.returncode == 0, (cell["id"], result.stderr)


def test_complete_notebook_with_real_oauth2c(lab):
    run(lab, "preflight")
    actor = run(lab, "actor")
    assert "synthetic-secret" not in actor.stdout
    run(lab, "callback-add")
    login(lab)
    run(lab, "exchange")
    run(lab, "vault-positive")
    run(lab, "vault-negative")
    run(lab, "autonomous")
    refresh = run(lab, "refresh")
    assert "omitido" in refresh.stdout
    inspected = run(lab, "inspect")
    assert "synthetic-password" in inspected.stdout
    assert "access_token" in inspected.stdout
    run(lab, "callback-remove")
    assert lab.server.app["providers"]["oidc"]["properties"]["redirectUris"] == [
        "http://localhost:8088/auth/callback"]
    assert not (lab.private / "callback.json").exists()
    assert not (lab.private / ".lock").exists()
    assert not list(lab.private.glob(".work.*"))
    for file in lab.private.glob("*.json"):
        assert file.stat().st_mode & 0o777 == 0o600


def test_callback_idempotence_and_preserves_other_edits(lab):
    run(lab, "callback-add")
    run(lab, "callback-add")
    assert sum(call[0] == "PUT" for call in lab.server.calls) == 1
    lab.server.app["description"] = "changed after setup"
    lab.server.app["providers"]["oidc"]["properties"]["redirectUris"].append("http://localhost:9000/other")
    run(lab, "callback-remove")
    assert lab.server.app["description"] == "changed after setup"
    assert lab.server.app["providers"]["oidc"]["properties"]["redirectUris"] == [
        "http://localhost:8088/auth/callback", "http://localhost:9000/other"]
    run(lab, "callback-remove")
    assert sum(call[0] == "PUT" for call in lab.server.calls) == 2


def test_preexisting_callback_is_never_removed(lab):
    lab.server.app["providers"]["oidc"]["properties"]["redirectUris"].append("http://localhost:9876/callback")
    run(lab, "callback-add")
    assert json.loads((lab.private / "callback.json").read_text())["added"] is False
    run(lab, "callback-remove")
    assert not any(call[0] == "PUT" for call in lab.server.calls)
    assert "http://localhost:9876/callback" in lab.server.app["providers"]["oidc"]["properties"]["redirectUris"]


def test_failed_token_request_cannot_leave_stale_result(lab):
    run(lab, "actor")
    (lab.private / "obo.json").write_text('{"access_token":"previous"}')
    lab.server.fail_tokens = True
    run(lab, "actor", success=False)
    assert not (lab.private / "actor.json").exists()
    assert not (lab.private / "obo.json").exists()
    assert not (lab.private / ".lock").exists()


@pytest.mark.parametrize("problem", ["expired", "wrong-issuer", "missing"])
def test_rejects_invalid_input_before_exchange(lab, problem):
    run(lab, "preflight")
    human = {"access_token": lab.server.token("human")}
    if problem == "expired":
        human["access_token"] = lab.server.token("human", exp=int(time.time()) - 1)
    elif problem == "wrong-issuer":
        human["access_token"] = lab.server.token("human", iss="https://other.invalid/oauth2")
    if problem != "missing":
        (lab.private / "human.json").write_text(json.dumps(human))
    result = run(lab, "exchange", success=False)
    assert not any(call[0] == "TOKEN" for call in lab.server.calls)
    assert not (lab.private / "obo.json").exists()
    assert "ERROR" in result.stderr


def test_refresh_example_with_synthetic_refresh_token(lab):
    run(lab, "preflight")
    (lab.private / "human.json").write_text(json.dumps({"refresh_token": "synthetic-refresh"}))
    run(lab, "refresh")
    assert (lab.private / "refreshed.json").is_file()
    assert lab.server.calls[-1][2]["grant_type"] == "refresh_token"


def test_non_authorization_failure_is_not_reported_as_denial(lab):
    run(lab, "preflight")
    (lab.private / "obo.json").write_text(json.dumps({"access_token": lab.server.token(
        "human", **{"actor-token": {"sub": "oidc"}})}))
    lab.env["VAULT_DENIED_ERROR"] = "TLS handshake timeout"
    result = run(lab, "vault-negative", success=False)
    assert "no fue la denegación 403" in result.stderr


def test_missing_credential_stops_before_oauth(lab):
    lab.env["FAIL_CREDENTIAL"] = "chatbot/oidc"
    run(lab, "actor", success=False)
    assert not lab.server.calls


def test_callback_from_another_installation_is_not_touched(lab):
    run(lab, "callback-add")
    marker = lab.private / "callback.json"
    data = json.loads(marker.read_text())
    data["application_id"] = "different-app"
    marker.write_text(json.dumps(data))
    before = len(lab.server.calls)
    run(lab, "callback-remove", success=False)
    assert len(lab.server.calls) == before
    assert marker.is_file()


def test_occupied_callback_port_is_detected_before_modifying_verify(lab):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 9876))
        listener.listen()
        result = run(lab, "callback-add", success=False)
    assert "9876 is in use" in result.stderr
    assert not lab.server.calls
