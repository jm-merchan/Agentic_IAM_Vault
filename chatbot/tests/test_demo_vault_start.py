"""Run the installer's waits with real kubectl against a delayed local API."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl is required")
@pytest.mark.parametrize("denied", [False, True])
def test_vault_waits_for_creation_before_running(tmp_path, denied):
    requests = {}
    paths = []

    class API(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            paths.append(self.path)
            path = urlparse(self.path).path
            status = 200
            if path == "/api":
                body = {"kind": "APIVersions", "versions": ["v1"]}
            elif path == "/apis":
                body = {"kind": "APIGroupList", "groups": []}
            elif path == "/api/v1":
                body = {
                    "kind": "APIResourceList", "groupVersion": "v1",
                    "resources": [{"name": "pods", "singularName": "pod",
                                   "namespaced": True, "kind": "Pod",
                                   "verbs": ["get", "list", "watch"]}],
                }
            elif path == "/api/v1/namespaces/vault":
                body = {"apiVersion": "v1", "kind": "Namespace",
                        "metadata": {"name": "vault"}, "status": {"phase": "Active"}}
            elif path.startswith("/api/v1/namespaces/vault/pods"):
                listing = path.endswith("/pods")
                query = parse_qs(urlparse(self.path).query)
                name = (query.get("fieldSelector", [""])[0].removeprefix("metadata.name=")
                        if listing else path.rsplit("/", 1)[-1])
                requests[name] = requests.get(name, 0) + 1
                # Simulate the controller creating each pod after the first GET.
                if denied or (requests[name] == 1 and not listing):
                    status = 403 if denied else 404
                    body = {"apiVersion": "v1", "kind": "Status",
                            "status": "Failure", "code": status,
                            "reason": "Forbidden" if denied else "NotFound",
                            "message": f'pods "{name}" unavailable'}
                else:
                    body = {"apiVersion": "v1", "kind": "Pod",
                            "metadata": {"name": name, "namespace": "vault",
                                         "uid": name, "resourceVersion": "1"},
                            "status": {"phase": "Running"}}
                    if listing:
                        body = {"apiVersion": "v1", "kind": "PodList",
                                "metadata": {"resourceVersion": "1"},
                                "items": [] if requests[name] == 1 else [body]}
            else:
                status, body = 404, {"kind": "Status", "code": 404}
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), API)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Exercise the exact commands in vault.sh, without installing resources.
        waits = [
            line.replace("--timeout=450s", "--timeout=3s")
            for line in (ROOT / "scripts/demo/vault.sh").read_text().splitlines()
            if line.startswith('"${K[@]}" -n vault wait ')
        ]
        script = (
            'K=(kubectl --kubeconfig /dev/null --server "$TEST_API" '
            '--cache-dir "$TEST_CACHE" --request-timeout=2s)\n'
            + "\n".join(waits)
        )
        result = subprocess.run(
            ["/bin/bash", "-eu", "-c", script],
            env={**os.environ, "TEST_API": f"http://127.0.0.1:{server.server_port}",
                 "TEST_CACHE": str(tmp_path / "cache")},
            capture_output=True, text=True, timeout=15,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    if denied:
        assert result.returncode != 0
        assert "Forbidden" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr + repr(paths)
        assert set(requests) == {"vault-0", "vault-1", "vault-2"}
        assert all(count > 1 for count in requests.values())
