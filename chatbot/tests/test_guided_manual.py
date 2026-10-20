"""Run the guided entrypoint and real reconciliation scripts against isolated services."""
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lumen_guided", ROOT / "scripts/manual/guided.py")
guided = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guided
spec.loader.exec_module(guided)


def test_every_step_has_real_source_and_chapter():
    assert len({item.id for item in guided.STEPS}) == len(guided.STEPS)
    for item in guided.STEPS:
        assert (ROOT / item.command[1]).is_file()
        assert (ROOT / "docs/manual" / (item.chapter + ".md")).is_file()
    ids = [item.id for item in guided.STEPS]
    assert ids.index("oidc") < ids.index("research") < ids.index("sts") < ids.index("agentes")
    assert ids.index("modelos") < ids.index("arrancar") < ids.index("probar-obo")
    assert all("rebuild" not in item.command and "demo.sh" not in item.command for item in guided.STEPS)


@pytest.fixture
def guide_lab(tmp_path, monkeypatch):
    root = tmp_path / "repo with spaces"
    (root / "scripts/manual").mkdir(parents=True)
    (root / "scripts/demo").mkdir(parents=True)
    for name in ("guided-run.sh", "guided.py", "paso-a-paso.sh"):
        shutil.copy(ROOT / "scripts/manual" / name, root / "scripts/manual" / name)
    shutil.copy(ROOT / "scripts/demo/common.sh", root / "scripts/demo/common.sh")
    (root / ".env").write_text("VERIFY_TENANT=https://fixture.verify.ibm.com\nVALUE=first\n")
    # demo.sh exports its real input path. Fixture subprocesses must load only
    # their synthetic configuration, including when pytest runs inside start.
    monkeypatch.setenv("DEMO_ENV_FILE", str(root / ".env"))
    (root / "scripts/manual/guided-actions.sh").write_text(
        '#!/bin/bash\nset -eu\nprintf "%s\\n" "$VALUE" >> "$LUMEN_STATE_DIR/calls"\n'
        'test ! -e "$LUMEN_STATE_DIR/fail"\n')
    base = tmp_path / "private state"
    base.mkdir()
    return guided.Guide(root, base)


def test_failure_resume_reloads_environment_and_does_not_advance(guide_lab):
    guide = guide_lab
    (guide.base / "fail").touch()
    assert guide.run(0) != 0
    assert guide.next_index(guide.load()) == 0
    assert guide.load()["steps"]["entorno"]["status"] == "failed"
    (guide.base / "fail").unlink()
    (guide.root / ".env").write_text("VERIFY_TENANT=https://fixture.verify.ibm.com\nVALUE=second\n")
    assert guide.run(0) == 0
    assert guide.next_index(guide.load()) == 1
    assert (guide.base / "calls").read_text().splitlines() == ["first", "second"]
    record = guide.load()["steps"]["entorno"]
    assert record["attempt"] == 2
    assert len(list((guide.private / "logs").glob("*.log"))) == 2
    assert guide.path.stat().st_mode & 0o777 == 0o600
    assert Path(record["log"]).stat().st_mode & 0o777 == 0o600
    assert guided.Guide(guide.root, guide.base).next_index(guide.load()) == 1


def test_execution_can_start_midway_without_certifying_earlier_steps(guide_lab):
    guide = guide_lab
    (guide.root / "scripts/manual/guided-actions.sh").write_text("exit 0\n")
    index = guide.select("openai-mapping")
    assert guide.run(index) == 0
    assert set(guide.load()["steps"]) == {"openai-mapping"}
    assert guide.next_index(guide.load()) == index + 1
    assert guide.run(index) == 0  # An explicit repeat is allowed.
    assert guide.load()["steps"]["openai-mapping"]["attempt"] == 2


def test_second_process_cannot_execute_a_concurrent_step(guide_lab):
    guide = guide_lab
    with guide.locked():
        with pytest.raises(ValueError, match="otro paso"):
            guide.run(0)
    assert not (guide.base / "calls").exists()


def test_cli_next_runs_one_step_and_noninteractive_menu_does_not_hang(guide_lab):
    guide = guide_lab
    env = dict(os.environ, LUMEN_STATE_DIR=str(guide.base))
    command = ["bash", str(guide.root / "scripts/manual/paso-a-paso.sh")]
    result = subprocess.run(command + ["siguiente"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert set(guide.load()["steps"]) == {"entorno"}
    result = subprocess.run(command, env=env, input="", capture_output=True, text=True)
    assert result.returncode != 0
    assert "terminal" in result.stderr
    assert (guide.base / "calls").read_text().splitlines() == ["first"]


@pytest.mark.parametrize("broken", ["env", "step", "missing_tenant"])
def test_bad_inputs_stop_before_executing_any_commands(guide_lab, broken):
    guide = guide_lab
    if broken == "env":
        (guide.root / ".env").write_text('touch "$LUMEN_STATE_DIR/should-not-run"\nUNFINISHED="quote\n')
    elif broken == "step":
        (guide.root / "scripts/manual/guided-actions.sh").write_text(
            'touch "$LUMEN_STATE_DIR/should-not-run"\nUNFINISHED="quote\n')
    else:
        (guide.root / ".env").write_text('unset VERIFY_TENANT\nVALUE=fixture\n')
    assert guide.run(0) != 0
    assert not (guide.base / "should-not-run").exists()
    assert not (guide.base / "calls").exists()
    log = Path(guide.load()["steps"]["entorno"]["log"]).read_text()
    assert "unbound variable" not in log
    assert guide.next_index(guide.load()) == 0


class Terminal:
    """Exercise the entrypoint with a real PTY and the user's zsh/Bash boundary."""
    def __init__(self, guide):
        self.fd, slave = pty.openpty()
        self.process = subprocess.Popen(
            ["/bin/zsh", "-f", "-c", 'exec /bin/bash "$1"', "test-shell",
             str(guide.root / "scripts/manual/paso-a-paso.sh")],
            cwd=guide.base,  # Not the repository; the path contains spaces.
            env=dict(os.environ, LUMEN_STATE_DIR=str(guide.base)),
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        self.buffer = b""

    def expect(self, value, timeout=12):
        wanted = value.encode()
        end = time.monotonic() + timeout
        while wanted not in self.buffer:
            remaining = end - time.monotonic()
            assert remaining > 0, self.buffer.decode(errors="replace")
            ready, _, _ = select.select([self.fd], [], [], remaining)
            assert ready, self.buffer.decode(errors="replace")
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                chunk = b""
            assert chunk, self.buffer.decode(errors="replace")
            self.buffer += chunk
        before, _, self.buffer = self.buffer.partition(wanted)
        return before.decode(errors="replace")

    def send(self, value):
        os.write(self.fd, value.encode())

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=5)
        os.close(self.fd)


@pytest.mark.skipif(not Path("/bin/zsh").exists(), reason="macOS zsh entrypoint")
def test_real_terminal_failure_exit_and_resume_from_zsh(guide_lab):
    guide = guide_lab
    (guide.base / "fail").touch()
    terminal = Terminal(guide)
    try:
        terminal.expect("[Enter / v / l / número / q] > ")
        terminal.send("01\n")  # Exact number as displayed by the menu.
        terminal.expect("[Enter / v / l / número / q] > ")
        terminal.send("\n")
        terminal.expect("El paso entorno no terminó.")
        terminal.expect("[Enter / v / l / número / q] > ")
        terminal.send("q\n")
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
    assert guide.next_index(guide.load()) == 0
    (guide.base / "fail").unlink()
    terminal = Terminal(guide)
    try:
        terminal.expect("01/34")
        terminal.expect("[Enter / v / l / número / q] > ")
        terminal.send("\n")
        terminal.expect("OK · entorno")
        terminal.expect("02/34")
        terminal.expect("[Enter / v / l / número / q] > ")
        terminal.send("q\n")
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
    assert (guide.base / "calls").read_text().splitlines() == ["first", "first"]
    assert set(guide.load()["steps"]) == {"entorno"}


@pytest.mark.skipif(not Path("/bin/zsh").exists(), reason="macOS zsh entrypoint")
def test_interrupting_step_stops_child_and_keeps_the_step_pending(guide_lab):
    guide = guide_lab
    (guide.root / "scripts/manual/guided-actions.sh").write_text(
        'printf "%s" "$$" > "$LUMEN_STATE_DIR/child.pid"\nexec sleep 120\n')
    terminal = Terminal(guide)
    try:
        terminal.expect("[Enter / v / l / número / q] > ")
        terminal.send("\n")
        terminal.expect("Log:")
        end = time.monotonic() + 5
        while not (guide.base / "child.pid").exists() and time.monotonic() < end:
            time.sleep(0.02)
        child = int((guide.base / "child.pid").read_text())
        terminal.process.send_signal(signal.SIGINT)
        terminal.expect("El paso entorno no terminó.")
        terminal.expect("[Enter / v / l / número / q] > ")
        terminal.send("q\n")
        assert terminal.process.wait(timeout=5) == 0
    finally:
        terminal.close()
    assert guide.next_index(guide.load()) == 0
    assert guide.load()["steps"]["entorno"]["exit_code"] == 130
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


# This service fixture models HTTP resources and KV state; it does not replace
# the jq programs, loops, identity selection or mutation decisions under test.
SERVICE = r'''
import json, os, re, sys
from pathlib import Path
file = Path(os.environ["SERVICE_STATE"])
state = json.loads(file.read_text())
args = sys.argv[1:]
state["calls"].append(args)
def save(): file.write_text(json.dumps(state))
def fail(message):
    save()
    raise SystemExit(message)
def out(value, path=None):
    if path: Path(path).write_text(json.dumps(value))
    else: print(json.dumps(value))
    save()
def user(username, uid):
    return {"id": uid, "userName": username, "active": True,
            "urn:ietf:params:scim:schemas:extension:ibm:2.0:User": {"pwdReset": True}}
if args[0] == "login":
    out(None)
elif args[0] == "kv-read":
    if args[1] not in state["kv"]: fail("missing credential")
    out(state["kv"][args[1]])
elif args[0] == "kv-write":
    state["kv"][args[1]] = json.load(sys.stdin)
    save()
elif args[0] == "vault":
    command = args[1:]
    if command[:2] == ["kv", "list"]:
        assert command == ["kv", "list", "-format=json", "-mount=secrets", "chatbot"]
        if state.get("vault_list_error"): fail("Vault unavailable")
        out([key.split("/")[-1] for key in state["kv"] if key.startswith("chatbot/")])
    elif command[:2] == ["policy", "read"]:
        if state.get("missing_policy") == command[-1]: fail("No such policy")
        out("fixture policy")
    elif command[0] == "write":
        path = command[1]
        if path.startswith("identity/entity/name/"):
            name = path.rsplit("/", 1)[-1]
            state.setdefault("entities", {}).setdefault(name, {"id": "entity-"+name, "aliases": []})
        elif path == "identity/entity-alias":
            data = dict(a.split("=", 1) for a in command[2:])
            entity = next(v for v in state["entities"].values() if v["id"] == data["canonical_id"])
            entity["aliases"].append({"id": "alias-"+data["name"], "name": data["name"]})
        elif path.startswith("identity/group/name/"):
            state.setdefault("vault_groups", {})[path.rsplit("/", 1)[-1]] = json.load(sys.stdin)
        else: fail("Unsupported Vault write")
        save()
    elif command[0] == "read":
        path = command[-1]
        if path.startswith("identity/entity/name/"):
            print(state["entities"][path.rsplit("/", 1)[-1]]["id"])
            save()
        else:
            assert path.startswith("identity/entity/id/")
            entity = next(v for v in state["entities"].values() if v["id"] == path.rsplit("/", 1)[-1])
            out({"data": entity})
    else: fail("Unsupported Vault command")
else:
    assert args[0] == "api"
    method, path, output = args[1:4]
    payload = None
    if "--data-binary" in args:
        payload = json.loads(Path(args[args.index("--data-binary")+1][1:]).read_text())
    if path.startswith("/v1.0/owner/applications/") and path.endswith("/entitlements"):
        assert method == "POST"
        state["grants"] = payload
        result = {}
    elif path.startswith("/v1.0/sts/oauth/clients"):
        if state.get("sts_list_error"): fail("HTTP 401")
        if path == "/v1.0/sts/oauth/clients":
            if method == "GET": result = {"clients": list(state["sts"].values())}
            else:
                assert method == "POST"
                uid = "new-sts"
                result = {**payload, "clientId": uid, "clientAuthentication": {"clientSecret": "synthetic-sts"}}
                state["sts"][uid] = result
                Path(os.environ["TMP_WORK"], "response.headers").write_text("HTTP/2 201\nLocation: /v1.0/sts/oauth/clients/" + uid + "\r\n")
                result = None
        else:
            uid = path.rsplit("/", 1)[-1]
            if method == "PUT": state["sts"][uid] = payload
            result = state["sts"][uid]
    elif path.startswith("/v1.0/applications"):
        if path == "/v1.0/applications":
            if method == "GET":
                result = {"_embedded": {"applications": [{"name": app["name"], "_links": {"self": {"href": path+"/"+uid}}} for uid, app in state["apps"].items()]}}
            else:
                assert method == "POST"
                uid = str(len(state["apps"])+1)
                payload["providers"]["oidc"]["properties"].update(clientId="cid-"+uid, clientSecret="synthetic-secret")
                state["apps"][uid] = payload
                result = {"id": uid}
        else:
            uid = path.rsplit("/", 1)[-1]
            if method == "PUT": state["apps"][uid] = payload
            result = state["apps"][uid]
    elif path.startswith("/v2.0/"):
        kind = path.split("/")[2]
        resources = state[kind]
        if len(path.split("/")) == 3:
            if method == "GET":
                query = args[args.index("--data-urlencode")+1]
                value = re.search(r'"(.*)"', query).group(1)
                field = "userName" if kind == "Users" else "displayName"
                result = {"Resources": [r for r in resources.values() if r[field] == value]}
            else:
                assert method == "POST"
                uid = kind+"-"+str(len(resources)+1)
                result = user(payload["userName"], uid) if kind == "Users" else {**payload, "id": uid}
                resources[uid] = result
        else:
            uid = path.rsplit("/", 1)[-1]
            result = resources[uid]
            if method == "PATCH":
                if kind == "Users":
                    result["urn:ietf:params:scim:schemas:extension:ibm:2.0:User"]["pwdReset"] = False
                else: result.setdefault("members", []).extend(payload["Operations"][0]["value"])
    else: fail("Unsupported API route")
    out(result, output)
'''


@pytest.fixture
def service_lab(tmp_path):
    root = tmp_path / "repo"
    scripts = root / "chatbot/scripts"
    scripts.mkdir(parents=True)
    (root / "chatbot/docs").mkdir()
    common = root / "verify/scripts/common.sh"
    common.parent.mkdir(parents=True)
    shutil.copytree(ROOT / "verify/config", root / "verify/config")
    for name in ("02-verify-apps.sh", "03-verify-users.sh", "05-sync-groups.sh", "configure-runtime.sh"):
        shutil.copy(ROOT / "chatbot/scripts" / name, scripts / name)
    work = tmp_path / "work"
    work.mkdir()
    common.write_text('''set -euo pipefail
VERIFY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fail() { echo "$*" >&2; exit 1; }
admin_login() { python3 "$SERVICE" login >/dev/null; }
api() { python3 "$SERVICE" api "$@"; }
kv_read() { python3 "$SERVICE" kv-read "$1"; }
kv_write() { python3 "$SERVICE" kv-write "$1"; }
TENANT=https://fixture.verify.ibm.com
''')
    service = tmp_path / "service.py"
    service.write_text(SERVICE)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    vault = bindir / "vault"
    vault.write_text('#!/bin/bash\nexec python3 "$SERVICE" vault "$@"\n')
    vault.chmod(0o700)
    state = tmp_path / "state.json"
    data = {"calls": [], "apps": {}, "sts": {}, "Users": {}, "Groups": {},
            "kv": {f"chatbot/users/{r}": {"username": "lumen-"+r, "password": "synthetic-password-"+r}
                   for r in ("reader", "writer", "supervisor")}}
    state.write_text(json.dumps(data))
    env = dict(os.environ, PATH=str(bindir)+os.pathsep+os.environ["PATH"],
               SERVICE=str(service), SERVICE_STATE=str(state), TMP_WORK=str(work))
    def run(script, *args):
        return subprocess.run(["bash", str(scripts / script), *args], env=env, capture_output=True, text=True)
    return state, run


@pytest.mark.parametrize("ids,saved,success", [
    ([], None, True), (["a"], None, True), (["a", "b"], "a", True),
    (["a", "b"], None, False), (["a"], "old", False),
])
def test_sts_resume_selects_saved_client_or_fails_without_writing(service_lab, ids, saved, success):
    state, run = service_lab
    data = json.loads(state.read_text())
    data["sts"] = {uid: {"clientName": "vault-chatbot-sts", "clientId": uid,
                         "clientAuthentication": {"clientSecret": "synthetic"}} for uid in ids}
    if saved: data["kv"]["chatbot/sts"] = {"client_id": saved, "client_secret": "synthetic"}
    state.write_text(json.dumps(data))
    result = run("02-verify-apps.sh", "sts")
    assert (result.returncode == 0) == success, result.stderr
    data = json.loads(state.read_text())
    writes = [c for c in data["calls"] if c[0] == "api" and c[1] in ("POST", "PUT", "DELETE")]
    if not success:
        assert writes == []
        return
    expected = saved or (ids[0] if ids else "new-sts")
    assert data["kv"]["chatbot/sts"]["client_id"] == expected
    assert all(c[1] != "DELETE" for c in writes)
    assert run("02-verify-apps.sh", "sts").returncode == 0
    data = json.loads(state.read_text())
    assert sum(c[:2] == ["api", "POST"] for c in data["calls"]) == (0 if ids else 1)
    assert sum(c[0] == "login" for c in data["calls"]) == 2


@pytest.mark.parametrize("failure", ["sts_list_error", "vault_list_error"])
def test_failed_inventory_never_creates_sts(service_lab, failure):
    state, run = service_lab
    data = json.loads(state.read_text())
    data[failure] = True
    state.write_text(json.dumps(data))
    assert run("02-verify-apps.sh", "sts").returncode != 0
    assert not any(c[:2] == ["api", "POST"] for c in json.loads(state.read_text())["calls"])


def test_research_can_be_repaired_alone_without_touching_sts_or_oidc(service_lab):
    state, run = service_lab
    for _ in range(2):
        result = run("02-verify-apps.sh", "research")
        assert result.returncode == 0, result.stderr
    data = json.loads(state.read_text())
    assert len(data["apps"]) == 1
    assert next(iter(data["apps"].values()))["name"] == "vault-chatbot-research"
    assert data["kv"]["chatbot/research"]["client_id"]
    assert "chatbot/oidc" not in data["kv"]
    assert not any("/sts/" in str(c) for c in data["calls"])
    assert sum(c[:2] == ["api", "POST"] for c in data["calls"]) == 1


@pytest.mark.parametrize("existing,pending", [(False, True), (True, True), (True, False)])
def test_user_resume_repairs_ids_without_recreating_or_repeating_password_patch(service_lab, existing, pending):
    state, run = service_lab
    data = json.loads(state.read_text())
    if existing:
        data["Users"] = {r: {"id": r, "userName": "lumen-"+r, "active": True,
                             "urn:ietf:params:scim:schemas:extension:ibm:2.0:User": {"pwdReset": pending}}
                         for r in ("reader", "writer", "supervisor")}
    state.write_text(json.dumps(data))
    for _ in range(2):
        result = run("03-verify-users.sh")
        assert result.returncode == 0, result.stderr
    data = json.loads(state.read_text())
    user_creates = [c for c in data["calls"] if c[:3] == ["api", "POST", "/v2.0/Users"]]
    resets = [c for c in data["calls"] if c[:2] == ["api", "PATCH"] and c[2].startswith("/v2.0/Users/")]
    assert len(user_creates) == (0 if existing else 3)
    assert len(resets) == (3 if pending else 0)
    assert len(data["Groups"]) == 3
    for role in ("reader", "writer", "supervisor"):
        credential = data["kv"]["chatbot/users/"+role]
        assert credential["user_id"]
        assert credential["password"] == "synthetic-password-"+role
    assert len(data["kv"]["chatbot/directory"]["users"]) == 3


def test_invalid_user_credential_stops_before_any_scim_write(service_lab):
    state, run = service_lab
    data = json.loads(state.read_text())
    data["kv"]["chatbot/users/supervisor"]["username"] = "someone-else"
    state.write_text(json.dumps(data))
    assert run("03-verify-users.sh").returncode != 0
    assert not any(c[0] == "api" for c in json.loads(state.read_text())["calls"])


def configured_groups(state):
    data = json.loads(state.read_text())
    data["kv"]["chatbot/runtime"] = {"session_secret": "preserve-existing-key",
                                    "groups": {}, "permission_probe": {"version": 1}}
    data["kv"]["chatbot/oidc"] = {"application_id": "oidc-app", "client_id": "cid"}
    for role in ("reader", "writer", "supervisor"):
        uid, gid = "u-"+role, "g-"+role
        data["Users"][uid] = {"id": uid, "userName": "lumen-"+role, "active": True}
        data["Groups"][gid] = {"id": gid, "displayName": "chatbot-"+role+"s",
                               "members": [{"value": uid, "type": "user"}]}
    state.write_text(json.dumps(data))


@pytest.mark.parametrize("missing", ["group", "policy", "runtime"])
def test_group_preflight_failure_does_not_partially_sync_first_groups(service_lab, missing):
    state, run = service_lab
    configured_groups(state)
    data = json.loads(state.read_text())
    if missing == "group":
        del data["Groups"]["g-supervisor"]
    elif missing == "policy":
        data["missing_policy"] = "chatbot-supervisor"
    else:
        del data["kv"]["chatbot/runtime"]
    before = json.loads(json.dumps(data["kv"]))
    state.write_text(json.dumps(data))
    result = run("05-sync-groups.sh")
    assert result.returncode != 0
    after = json.loads(state.read_text())
    assert after["kv"] == before
    assert not any(c[:2] in (["vault", "write"], ["api", "POST"], ["kv-write", "chatbot/runtime"])
                   for c in after["calls"])


def test_group_check_only_reads_and_sync_preserves_session_secret(service_lab):
    state, run = service_lab
    configured_groups(state)
    before = json.loads(state.read_text())["kv"]
    result = run("05-sync-groups.sh", "--check")
    assert result.returncode == 0, result.stderr
    checked = json.loads(state.read_text())
    assert checked["kv"] == before
    assert "entities" not in checked and "vault_groups" not in checked and "grants" not in checked
    for _ in range(2):
        result = run("05-sync-groups.sh")
        assert result.returncode == 0, result.stderr
    data = json.loads(state.read_text())
    assert data["kv"]["chatbot/runtime"]["session_secret"] == "preserve-existing-key"
    assert data["kv"]["chatbot/runtime"]["permission_probe"] == {"version": 1}
    for role, level in (("reader", "readonly"), ("writer", "readwrite"), ("supervisor", "sensitive")):
        group = "chatbot-"+role+"s"
        assert data["kv"]["chatbot/runtime"]["groups"][level] == [group, "g-"+role]
        assert data["vault_groups"][group] == {
            "type": "internal", "policies": ["chatbot-"+role],
            "member_entity_ids": ["entity-chatbot-human-u-"+role]}
        assert len(data["entities"]["chatbot-human-u-"+role]["aliases"]) == 1
    assert len(data["grants"]["additions"]) == 3


@pytest.mark.parametrize("existing", [False, True])
def test_runtime_creation_and_repeat_preserve_the_session_key(service_lab, existing):
    state, run = service_lab
    if existing:
        configured_groups(state)
    for _ in range(2):
        result = run("configure-runtime.sh")
        assert result.returncode == 0, result.stderr
        current = json.loads(state.read_text())["kv"]["chatbot/runtime"]["session_secret"]
        if _ == 0:
            first = current
        else:
            assert current == first
    if existing:
        assert first == "preserve-existing-key"
