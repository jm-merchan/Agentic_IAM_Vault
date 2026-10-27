# Vault 2.2.0 images with the xAI plugin

Both editions are published to the existing Docker Hub repository
[`josemerchan/vault-xai`](https://hub.docker.com/r/josemerchan/vault-xai/tags).
Both contain the plugin for `linux/amd64` and `linux/arm64`.

| Image | Binary version | Use |
|---|---|---|
| `josemerchan/vault-xai:2.2.0-ent` | `2.2.0+ent` | Enterprise; requires a license with the features used |
| `josemerchan/vault-xai:2.2.0` | `2.2.0` | Community; does not replace Enterprise in the full demo |

The container tag uses `-ent`, like the official images, while the
binary shows `+ent`. Lumen needs Enterprise for Agentic IAM, namespaces,
KMIP and Transform.

Publishing **does not upgrade an existing cluster**. The deployment uses
`2.2.0-ent` by default; the version is defined only once in
[`deploy/vault-image.conf`](../deploy/vault-image.conf), which the build,
the image tests and the launcher read. `VAULT_IMAGE_TAG` in `.env` overrides it.
A cluster created with another version requires a separate Raft migration.

## Reproducing the build

You need Podman, Go, jq and the plugin repository. The script uses only
its committed Git revision and rejects pending changes in tracked files;
the binaries are compiled from that revision in a temporary context.

```bash
bash scripts/build-vault-images.sh --build
```

By default it reads `$HOME/Projects/vault-plugin-secrets-xai`. Another
path can be chosen with `XAI_PLUGIN_REPO`. `VAULT_PUBLISH_REPOSITORY` selects
the destination; the default value is `docker.io/josemerchan/vault-xai`.

To test the Enterprise edition, prepare a private license file
from the demo configuration:

```bash
bash -c 'source scripts/demo/common.sh; load_inputs; mkdir -p "$LUMEN_STATE_DIR/images/vault-2.2.0"; printf "VAULT_LICENSE=%s\n" "$VAULT_LICENSE" > "$LUMEN_STATE_DIR/images/vault-2.2.0/license.env"'
```

```bash
bash scripts/test-vault-images.sh
```

It starts four isolated dev servers, with no published ports. Each one
registers and loads the plugin; when it finishes, it removes only its own containers.
It does not call xAI or connect to the Lumen cluster.

Publishing, with the Podman session authenticated to Docker Hub, builds and
tests both editions before pushing their manifests:

```bash
bash scripts/build-vault-images.sh --publish
```

Repeating `--publish` replaces those same two tags with the
verified build. It does not write `latest` or change earlier tags.
The license is used only in the test containers; it does not enter the
build context or the published images.

```bash
rm -f "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/images/vault-2.2.0/license.env"
```

See [the publication report](vault-images-2.2.0.json) for the digests,
the plugin revision and the manifests verified on Docker Hub. The image tests
cover startup and plugin loading; they are not a test of a
Raft, KMIP or federation migration of an existing cluster.

References: [Vault 2.x release notes](https://developer.hashicorp.com/vault/docs/updates/release-notes)
and [important changes](https://developer.hashicorp.com/vault/docs/updates/important-changes).
