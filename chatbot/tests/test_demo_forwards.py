"""Exercise forward replacement with shell doubles; never signal real processes."""
import os
from pathlib import Path
import subprocess

import pytest


COMMON = Path(__file__).resolve().parents[2] / 'scripts/demo/common.sh'
SCRIPT = r'''
source "$FORWARD_TEST_COMMON"
port_pid() {
  case "$(cat "$LUMEN_STATE_DIR/listener")" in
    initial) printf '%s\n' "$FORWARD_TEST_PID";;
    managed) printf '424243\n';;
    *) return 1;;
  esac
}
ps() { printf '%s\n' "$FORWARD_TEST_COMMAND"; }
unload_managed() { printf 'unload:%s\n' "$1" >> "$LUMEN_STATE_DIR/events"; }
kill() {
  printf 'stop:%s\n' "$1" >> "$LUMEN_STATE_DIR/events"
  printf 'stopped\n' > "$LUMEN_STATE_DIR/listener"
}
start_managed() {
  printf 'start:%s\n' "$1" >> "$LUMEN_STATE_DIR/events"
  printf 'managed\n' > "$LUMEN_STATE_DIR/listener"
}
start_forward tempo lumen-observability svc/tempo 3200 3200
'''


@pytest.mark.parametrize('listener,pid,command,success,stop', [
    ('initial', '424242', 'kubectl --context workshop -n lumen-observability port-forward --address 127.0.0.1 svc/tempo 3200:3200', True, True),
    ('absent', '', '', True, False),
    ('initial', '424242', 'kubectl --context another-cluster -n lumen-observability port-forward svc/tempo 3200:3200', False, False),
    ('initial', '424242', 'kubectl --context workshop -n another-namespace port-forward svc/tempo 3200:3200', False, False),
    ('initial', '424242', 'python -m http.server 3200', False, False),
    ('initial', '424242\n424244', 'kubectl --context workshop -n lumen-observability port-forward svc/tempo 3200:3200', False, False),
])
def test_start_rebinds_only_matching_forward(tmp_path, listener, pid, command, success, stop):
    (tmp_path / 'pids').mkdir()
    (tmp_path / 'listener').write_text(listener)
    (tmp_path / 'events').write_text('')
    env = {
        **os.environ,
        'FORWARD_TEST_COMMON': str(COMMON),
        'LUMEN_STATE_DIR': str(tmp_path),
        'FORWARD_TEST_PID': pid,
        'FORWARD_TEST_COMMAND': command,
    }
    result = subprocess.run(['bash', '-c', SCRIPT], env=env, capture_output=True,
                            text=True, timeout=10)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    expected = (['unload:tempo', 'stop:424242'] if stop else []) + (['start:tempo'] if success else [])
    assert (tmp_path / 'events').read_text().splitlines() == expected
    if success:
        assert (tmp_path / 'pids/tempo.pid').read_text().strip() == '424243'
