#!/usr/bin/env bash
# Isolated dev servers: no host ports, existing cluster, or provider calls.
set -euo pipefail
umask 077
source "$(dirname "$0")/../deploy/vault-image.conf"
version=$VAULT_IMAGE_VERSION
state=${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/images/vault-$version
license_file=${VAULT_TEST_LICENSE_FILE:-$state/license.env}
[ -s "$license_file" ] || { echo 'Set VAULT_TEST_LICENSE_FILE to a private VAULT_LICENSE env file.' >&2; exit 1; }
container=''
cleanup() { if [ -n "$container" ]; then podman rm -f "$container" >/dev/null 2>&1 || true; fi; }
trap cleanup EXIT
for tag in "$version" "$version-ent"; do
  for arch in amd64 arm64; do
    container="lumen-build-check-${tag}-${arch}-$$"
    podman run -d --name "$container" --platform "linux/$arch" --cap-add IPC_LOCK \
      --env-file "$license_file" --env VAULT_ADDR=http://127.0.0.1:8200 --env VAULT_TOKEN=isolated-build-test \
      --entrypoint vault "localhost/lumen-vault-build:$tag-$arch" server \
      -dev -dev-root-token-id=isolated-build-test -dev-listen-address=127.0.0.1:8200 \
      -config=/vault/config/plugins.hcl > /dev/null
    ready=false
    for attempt in $(seq 1 30); do
      if podman exec "$container" vault status -format=json > "$state/status-$tag-$arch.json" 2>/dev/null; then ready=true; break; fi
      sleep 1
    done
    "$ready" || { echo "Dev server failed: $tag/$arch" >&2; exit 1; }
    podman exec "$container" sh -ec '
      checksum=$(cat /vault/plugins/vault-plugin-secrets-xai.sha256)
      vault plugin register -sha256="$checksum" secret vault-plugin-secrets-xai >/dev/null
      vault secrets enable -path=xai vault-plugin-secrets-xai >/dev/null
      vault path-help xai/roles >/dev/null
      vault read -format=json sys/plugins/catalog/secret/vault-plugin-secrets-xai
    ' > "$state/plugin-$tag-$arch.json"
    jq -e '.data.command=="vault-plugin-secrets-xai" and (.data.sha256|length==64)' "$state/plugin-$tag-$arch.json" >/dev/null
    printf '%s linux/%s: isolated server and xAI plugin OK\n' "$tag" "$arch"
    cleanup
    container=''
  done
done
