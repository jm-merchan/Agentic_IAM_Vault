"""A failed Claude exchange must prevent a successful installation report."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("sync_status,claude_status", [(0, 0), (0, 42), (42, 0)])
def test_start_requires_real_claude_verification(tmp_path, sync_status, claude_status):
    root = tmp_path / "repo"
    root.mkdir()
    demo = (ROOT / "demo.sh").read_text()
    # Isolate every provisioning command, while running the real orchestrator.
    for name in re.findall(r'\$DEMO_ROOT/([^"\s]+\.sh)', demo):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("exit 0\n")
    shutil.copy(ROOT / "scripts/demo/common.sh", root / "scripts/demo/common.sh")
    (root / "scripts/demo/model-provider.sh").write_text(
        "select_model_provider() { export LUMEN_SELECTED_PROVIDER=openai; }\n")
    (root / "chatbot/scripts/verify-anthropic.sh").write_text(
        f"printf checked > \"$LUMEN_STATE_DIR/claude-checked\"\nexit {claude_status}\n")
    (root / "scripts/demo/claude-issuer.sh").write_text(
        f"printf checked > \"$LUMEN_STATE_DIR/claude-synced\"\nexit {sync_status}\n")
    python = root / "test-python"
    python.write_text("#!/bin/bash\nexit 0\n")
    python.chmod(0o700)
    (root / "demo.sh").write_text(
        demo.replace("/tmp/vault-chatbot-venv/bin/python", str(python)))
    env_file = root / ".env"
    env_file.write_text("VERIFY_TENANT=https://fixture.verify.ibm.com\n")
    state = tmp_path / "state"
    result = subprocess.run(
        ["/bin/bash", str(root / "demo.sh"), "start"],
        env={**os.environ, "DEMO_ENV_FILE": str(env_file),
             "LUMEN_STATE_DIR": str(state)},
        capture_output=True, text=True, timeout=15,
    )
    report = json.loads((state / "last-run.json").read_text())
    assert (state / "claude-synced").read_text() == "checked"
    assert (state / "claude-checked").exists() is (sync_status == 0)
    assert report["completed"] is (claude_status == 0 and sync_status == 0)
    assert (result.returncode == 0) is report["completed"]
    if sync_status or claude_status:
        assert report["steps"][-1] == {
            "name": ("Claves públicas del emisor Claude (API o consola)" if sync_status
                     else "Claude: federación SPIFFE e inferencia real"), "passed": False}
        assert "Demo lista" not in result.stdout


def test_failed_verification_exports_only_public_keys_and_recovery_steps(tmp_path):
    chatbot = tmp_path / "chatbot"
    (chatbot / "scripts").mkdir(parents=True)
    (chatbot / "docs").mkdir()
    report = chatbot / "docs/anthropic-spiffe-verification.json"
    report.write_text('{"all_passed":true}')
    config = tmp_path / "vault.env"
    config.write_text("VAULT_ADDR=https://fixture\nVAULT_CACERT=fixture\nVAULT_TOKEN=synthetic-root\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    vault = bindir / "vault"
    vault.write_text("""#!/bin/bash
if [ "$1" = read ]; then
  printf '%s\\n' '{"data":{"keys":[{"kty":"RSA","kid":"new-key","n":"public","e":"AQAB","d":"PRIVATE-CANARY"}]}}'
elif [ "$1" = token ]; then
  printf '%s\\n' '{"auth":{"client_token":"synthetic-bootstrap"}}'
else
  exit 99
fi
""")
    vault.chmod(0o700)
    python = bindir / "python"
    python.write_text("#!/bin/bash\ncat >/dev/null\necho 'synthetic HTTP 401' >&2\nexit 42\n")
    python.chmod(0o700)
    script = chatbot / "scripts/verify-anthropic.sh"
    script.write_text((ROOT / "chatbot/scripts/verify-anthropic.sh").read_text().replace(
        "/tmp/vault-chatbot-venv/bin/python", str(python)))
    state = tmp_path / "state"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env={**os.environ, "VAULT_ENV_FILE": str(config),
             "LUMEN_STATE_DIR": str(state), "PATH": str(bindir)+os.pathsep+os.environ["PATH"]},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 42
    assert not report.exists()
    keys = (state / "claude/issuer-keys.json").read_text()
    assert json.loads(keys)[0]["kid"] == "new-key"
    assert "PRIVATE-CANARY" not in keys + result.stdout + result.stderr
    assert "issuer-keys.json" in result.stderr
    assert "https://platform.claude.com/settings/workload-identity-federation" in result.stderr
    assert "./demo.sh start" in result.stderr
