#!/usr/bin/env bash
# Build both editions from a committed plugin checkout. Publishing is explicit.
set -euo pipefail
umask 077
source "$(dirname "$0")/../deploy/vault-image.conf"
version=$VAULT_IMAGE_VERSION
plugin_repo=${XAI_PLUGIN_REPO:-$HOME/Projects/vault-plugin-secrets-xai}
repository=${VAULT_PUBLISH_REPOSITORY:-docker.io/josemerchan/vault-xai}
publish=false
case "${1:-}" in ''|--build) ;; --publish) publish=true ;; *) echo 'Usage: build-vault-images.sh [--build|--publish]' >&2; exit 2;; esac
for command in git go podman jq; do command -v "$command" >/dev/null; done
git -C "$plugin_repo" diff --quiet
git -C "$plugin_repo" diff --cached --quiet
revision=$(git -C "$plugin_repo" rev-parse HEAD)
state=${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/images/vault-$version
mkdir -p "$state"
context=$(mktemp -d "$state/source.XXXXXX")
trap 'rm -rf "$context"' EXIT
git -C "$plugin_repo" archive "$revision" | tar -x -C "$context"
(
  cd "$context"
  go test ./...
  make linux-bins
)
for edition in community enterprise; do
  tag=$version
  base=docker.io/hashicorp/vault:$version
  if [ "$edition" = enterprise ]; then
    tag=$version-ent
    base=docker.io/hashicorp/vault-enterprise:$tag
  fi
  for arch in amd64 arm64; do
    image=localhost/lumen-vault-build:$tag-$arch
    podman build --platform "linux/$arch" \
      --build-arg "BASE_IMAGE=$base" --build-arg "TARGETARCH=$arch" \
      --label "org.opencontainers.image.revision=$revision" \
      --label "org.opencontainers.image.source=https://github.com/jm-merchan/vault-plugin-secrets-xai" \
      --label "org.opencontainers.image.version=$tag" \
      -t "$image" "$context" > "$state/build-$tag-$arch.log" 2>&1
    podman run --rm --platform "linux/$arch" --entrypoint sh "$image" -ec \
      'vault version; test -x /vault/plugins/vault-plugin-secrets-xai; cd /vault/plugins; printf "%s  vault-plugin-secrets-xai\n" "$(cat vault-plugin-secrets-xai.sha256)" | sha256sum -c -' \
      > "$state/check-$tag-$arch.txt"
    cat "$state/check-$tag-$arch.txt"
  done
  manifest=localhost/lumen-vault-build:$tag
  if podman manifest exists "$manifest"; then podman manifest rm "$manifest" >/dev/null; fi
  podman manifest create "$manifest" \
    "localhost/lumen-vault-build:$tag-amd64" "localhost/lumen-vault-build:$tag-arm64" >/dev/null
  podman manifest inspect "$manifest" > "$state/manifest-$tag.json"
  jq -e '[.manifests[].platform | .os+"/"+.architecture] | sort == ["linux/amd64","linux/arm64"]' \
    "$state/manifest-$tag.json" >/dev/null
done
if "$publish"; then
  bash "$(dirname "$0")/test-vault-images.sh"
  for tag in "$version" "$version-ent"; do
    podman manifest push --all --digestfile "$state/digest-$tag.txt" "localhost/lumen-vault-build:$tag" "docker://$repository:$tag"
    podman manifest inspect "$repository:$tag" > "$state/published-$tag.json"
    jq -e '[.manifests[].platform | .os+"/"+.architecture] | sort == ["linux/amd64","linux/arm64"]' \
      "$state/published-$tag.json" >/dev/null
  done
fi
jq -n --arg version "$version" --arg revision "$revision" --arg repository "$repository" \
  --argjson published "$publish" \
  '{version:$version,plugin_revision:$revision,repository:$repository,published:$published,platforms:["linux/amd64","linux/arm64"]}' \
  > "$state/result.json"
echo "Image evidence: $state"
