# 01 · Deploy and initialize Vault

[Index](README.md) · Requires [00](00-entorno.md) · Next: [MySQL](02-mysql.md)

## 1. Start Minikube

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
if minikube status -p workshop -o json > "$MANUAL/minikube-status.json" 2>/dev/null &&
   jq -e '.Host=="Running" and .APIServer=="Running"' "$MANUAL/minikube-status.json" >/dev/null; then
  printf 'The workshop profile is already running.\n'
else
  minikube start -p workshop --driver="${MINIKUBE_DRIVER:-podman}" \
    --memory="${MINIKUBE_MEMORY:-8192}" --cpus="${MINIKUBE_CPUS:-4}"
fi
"${K[@]}" get nodes -o wide
node_epoch=$(minikube ssh -p workshop -- date -u +%s </dev/null | tr -d '\r\n')
skew=$(( $(date -u +%s) - node_epoch ))
if [ "$skew" -gt 5 ] || [ "$skew" -lt -5 ]; then
  if [ "${CONTAINER_ENGINE:-podman}" != podman ]; then
    printf 'Synchronize the container VM clock before continuing (skew %s s).\n' "$skew" >&2
    exit 1
  fi
  podman machine ssh "${PODMAN_MACHINE:-podman-machine-default}" \
    sudo -n date -u -s "@$(date -u +%s)" </dev/null
  # Restart the active NTP service to discard pending adjustments from the previous clock.
  podman machine ssh "${PODMAN_MACHINE:-podman-machine-default}" \
    'if systemctl is-active --quiet chronyd; then sudo -n systemctl restart chronyd; fi' </dev/null
  node_epoch=$(minikube ssh -p workshop -- date -u +%s </dev/null | tr -d '\r\n')
  skew=$(( $(date -u +%s) - node_epoch ))
fi
[ "$skew" -le 5 ] && [ "$skew" -ge -5 ]
```

An existing profile keeps its CPUs/memory; `minikube start` does not resize it. The check avoids unnecessary restarts and downloads when the profile is already available. If the Mac was asleep, the step synchronizes the Podman VM when the skew exceeds 5 seconds and restarts `chronyd` if it was active. The threshold is lower than the OAuth profile's 15-second tolerance; checking only 60 seconds let through an environment that rejected freshly issued JWTs. `PODMAN_MACHINE` lets you select another Podman VM. Repeat this step before testing OIDC/OBO if there was a pause or sleep.

To explicitly synchronize this demo's Podman VM and then repeat the check:

```bash
podman machine ssh podman-machine-default sudo -n date -u -s "@$(date -u +%s)" </dev/null
podman machine ssh podman-machine-default \
  'if systemctl is-active --quiet chronyd; then sudo -n systemctl restart chronyd; fi' </dev/null
```

## 2. Create TLS and the Kubernetes secrets

This step applies to a new deployment. If `vault-ha-tls` already exists, keep its CA/certificate and the cluster's recovery keys; do not generate others on top of them.

```bash
export VSTATE="$LUMEN_STATE_DIR/vault"
"${K[@]}" create namespace vault --dry-run=client -o yaml | "${K[@]}" apply -f -
test ! -e "$VSTATE/vault.key"
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
  -subj '/CN=Lumen Vault Lab CA' -keyout "$VSTATE/ca.key" -out "$VSTATE/vault.ca"
openssl req -newkey rsa:2048 -nodes -sha256 \
  -subj '/CN=vault.vault.svc.cluster.local' \
  -keyout "$VSTATE/vault.key" -out "$VSTATE/vault.csr"
cat > "$VSTATE/extensions.cnf" <<'CONF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=DNS:localhost,DNS:vault,DNS:vault.vault.svc,DNS:vault.vault.svc.cluster.local,DNS:*.vault-internal,DNS:*.vault-internal.vault.svc.cluster.local,IP:127.0.0.1
CONF
openssl x509 -req -in "$VSTATE/vault.csr" \
  -CA "$VSTATE/vault.ca" -CAkey "$VSTATE/ca.key" -CAcreateserial \
  -out "$VSTATE/vault.crt" -days 825 -sha256 -extfile "$VSTATE/extensions.cnf"
"${K[@]}" -n vault create secret generic vault-ha-tls \
  --from-file="vault.key=$VSTATE/vault.key" \
  --from-file="vault.crt=$VSTATE/vault.crt" \
  --from-file="vault.ca=$VSTATE/vault.ca"
printf '%s' "$VAULT_LICENSE" > "$MANUAL/license"
"${K[@]}" -n vault create secret generic vault-ent-license \
  --from-file="license=$MANUAL/license"
rm -- "$MANUAL/license"
```

## 3. Install Vault Enterprise with Raft

[deploy/vault-values.yaml](../../deploy/vault-values.yaml) defines three Raft replicas, TLS, `retry_join`, plugin directory, persistent storage and UI. Injector and CSI are disabled. Review and apply that manifest:

```bash
cat deploy/vault-values.yaml
helm repo add hashicorp https://helm.releases.hashicorp.com --force-update
helm repo update hashicorp
helm upgrade --install vault hashicorp/vault --version "${VAULT_HELM_VERSION:-0.34.1}" \
  --kube-context workshop -n vault -f deploy/vault-values.yaml \
  --set-string server.image.repository=josemerchan/vault-xai \
  --set-string server.image.tag=2.2.0-ent --server-side=false
"${K[@]}" -n vault wait --for=create pod/vault-0 --timeout=450s
"${K[@]}" -n vault wait --for=create pod/vault-1 --timeout=450s
"${K[@]}" -n vault wait --for=create pod/vault-2 --timeout=450s
"${K[@]}" -n vault wait --for=jsonpath='{.status.phase}'=Running \
  pod/vault-0 pod/vault-1 pod/vault-2 --timeout=450s
```

Helm may finish before the controller creates the pods. First the block waits
for each pod to exist separately and then for all three to be `Running`.
`Running` does not mean initialized or unsealed. `--server-side=false` is used for compatibility with Helm 4 in this demo.

## 4. Initialize only once and unseal

The init response contains the root token and the unseal key. The 1/1 scheme simplifies this lab.

```bash
"${K[@]}" -n vault exec vault-0 -- vault status -format=json \
  > "$MANUAL/vault-status.json" || [ "$?" -eq 2 ]
if jq -e '.initialized==false' "$MANUAL/vault-status.json" >/dev/null; then
  test ! -s "$VSTATE/cluster-keys.json"
  "${K[@]}" -n vault exec vault-0 -- vault operator init \
    -key-shares=1 -key-threshold=1 -format=json > "$VSTATE/cluster-keys.json"
fi
test -s "$VSTATE/cluster-keys.json"
chmod 600 "$VSTATE/cluster-keys.json"
for pod in vault-0 vault-1 vault-2; do
  for attempt in $(seq 1 30); do
    "${K[@]}" -n vault exec "$pod" -- vault status -format=json \
      > "$MANUAL/vault-status.json" || [ "$?" -eq 2 ]
    if jq -e '.initialized and (.sealed|not)' "$MANUAL/vault-status.json" >/dev/null; then break; fi
    jq '{key:.unseal_keys_b64[0]}' "$VSTATE/cluster-keys.json" | \
      "${K[@]}" -n vault exec -i "$pod" -- vault write -format=json sys/unseal - \
      > "$MANUAL/unseal.json" 2> "$MANUAL/unseal-error.log" || true
    sleep 2
  done
  "${K[@]}" -n vault exec "$pod" -- vault status -format=json | \
    jq -e '.initialized and (.sealed|not)'
done
```

`vault write sys/unseal -` is the CLI equivalent that lets you send the key via stdin. The followers join through `retry_join`. If it was already initialized and you do not have its keys, recover the correct bootstrap; do not initialize again or delete its PVCs.

## 5. Connect Vault CLI from the Mac

In a **second terminal** keep this port-forward running; do not start another one if the port is already managed by `demo.sh`:

```bash
kubectl --context workshop -n vault port-forward --address 127.0.0.1 pod/vault-0 8443:8200
```

In the configuration terminal:

```bash
{
  printf 'VAULT_ADDR=%q\n' https://127.0.0.1:8443
  printf 'VAULT_CACERT=%q\n' "$VSTATE/vault.ca"
  printf 'VAULT_TOKEN=%q\n' "$(jq -er .root_token "$VSTATE/cluster-keys.json")"
} > "$VSTATE/config.env"
chmod 600 "$VSTATE/config.env"
source "$VSTATE/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=''
vault status
vault operator raft list-peers
vault read -format=json sys/license/status | jq '.data.autoloaded.features'
```

Result: three peers, Vault unsealed and the Agentic IAM/KMIP/Transform features available. UI: `https://127.0.0.1:8443/ui/`; trust the lab CA and use Token as the sign-in method. To copy the token on macOS without printing it: `printf '%s' "$VAULT_TOKEN" | pbcopy`.

## 6. Namespace and provisioning secrets

Check `vault namespace list` and `vault secrets list` before enabling resources that may already exist. In a new installation:

```bash
vault namespace create verify
export VAULT_NAMESPACE=verify
vault secrets enable -path=secrets -version=2 kv
jq -n '{client_id:env.VERIFY_ADMIN_CLIENT_ID,client_secret:env.VERIFY_ADMIN_CLIENT_SECRET,tenant:env.VERIFY_TENANT}' | \
  vault kv put -mount=secrets verify-admin -
jq -n '{TAVILY_API_KEY:env.TAVILY_API_KEY}' | vault kv put -mount=secrets tavily -
if [ -n "${XAI_MANAGEMENT_API_KEY:-}" ]; then
  jq -n '{API_KEY:env.XAI_MANAGEMENT_API_KEY}' | vault kv put -mount=secrets xai_mgmt -
fi
if [ -n "${OPENAI_ADMIN_API_KEY:-}" ]; then
  jq -n '{api_key:env.OPENAI_ADMIN_API_KEY}' | vault kv put -mount=secrets openai-admin -
fi
for role in reader writer supervisor; do
  name="LUMEN_$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')_PASSWORD"
  jq -n --arg role "$role" --arg name "$name" \
    '{username:("lumen-"+$role),password:env[$name],provider:"Cloud Directory"}' | \
    vault kv put -mount=secrets "chatbot/users/$role" -
done
vault secrets list
vault kv metadata get -mount=secrets verify-admin
```

The CLI name `secrets/verify-admin` corresponds to the API/ACL path `secrets/data/verify-admin`, because the engine is KV v2. They are not two different secrets.

Local sources: [vault.sh](../../scripts/demo/vault.sh), [bootstrap.sh](../../scripts/demo/bootstrap.sh).
