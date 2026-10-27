#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
VSTATE="$LUMEN_STATE_DIR/vault"
minikube_status=$(minikube status -p workshop -o json 2>/dev/null || true)
if [ "$(jq -r '.Host? // empty' <<<"$minikube_status" 2>/dev/null)" = Nonexistent ]; then
  fail 'The minikube profile workshop exists but its container is gone. Check that nothing else uses it, then run: minikube delete -p workshop'
fi
if ! jq -e '.Host=="Running" and .APIServer=="Running"' <<<"$minikube_status" >/dev/null 2>&1; then
  minikube start -p workshop --driver="${MINIKUBE_DRIVER:-podman}" --memory="${MINIKUBE_MEMORY:-8192}" --cpus="${MINIKUBE_CPUS:-4}"
fi
# A VM resumed after macOS sleep can lag behind the host. Check before issuing
# TLS certificates or initializing Vault; never work around it with insecure TLS.
node_epoch=$(minikube ssh -p workshop -- date -u +%s </dev/null | tr -d '\r\n')
[[ "$node_epoch" =~ ^[0-9]+$ ]] || fail 'No se pudo comprobar el reloj de Minikube'
clock_skew=$(( $(date -u +%s) - node_epoch ))
if [ "$clock_skew" -gt 60 ] || [ "$clock_skew" -lt -60 ]; then
  fail "El reloj de Minikube difiere ${clock_skew}s del host. Sincroniza la VM antes de continuar; consulta Reloj de la VM en docs/OPERACION.md."
fi
arch=$("${K[@]}" get nodes -o json | jq -er '.items[0].status.nodeInfo.architecture')
case "$arch" in amd64|arm64) ;; *) fail "Arquitectura no soportada: $arch";; esac
image_repo=${VAULT_IMAGE_REPOSITORY:-josemerchan/vault-xai}
source "$DEMO_ROOT/deploy/vault-image.conf"
image_tag=${VAULT_IMAGE_TAG:-$VAULT_IMAGE_VERSION-ent}

# Adopt the previous notebooks' keys before doing anything to an existing cluster.
if "${K[@]}" -n vault get statefulset vault >/dev/null 2>&1 && [ ! -s "$VSTATE/cluster-keys.json" ] && [ -s /tmp/vault/cluster-keys.json ]; then
  cp /tmp/vault/cluster-keys.json "$VSTATE/cluster-keys.json"
  chmod 600 "$VSTATE/cluster-keys.json" /tmp/vault/cluster-keys.json
  [ ! -f /tmp/vault/config.env ] || chmod 600 /tmp/vault/config.env
fi
if ! "${K[@]}" -n vault get statefulset vault >/dev/null 2>&1; then
  # Kubernetes pulls the published multi-architecture image directly from Docker Hub.
  "${K[@]}" create namespace vault --dry-run=client -o yaml | "${K[@]}" apply -f -
  if [ ! -s "$VSTATE/vault.crt" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 -subj '/CN=Lumen Vault Lab CA' -keyout "$VSTATE/ca.key" -out "$VSTATE/vault.ca"
    openssl req -newkey rsa:2048 -nodes -sha256 -subj '/CN=vault.vault.svc.cluster.local' -keyout "$VSTATE/vault.key" -out "$VSTATE/vault.csr"
    cat > "$VSTATE/extensions.cnf" <<'CONF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=DNS:localhost,DNS:vault,DNS:vault.vault.svc,DNS:vault.vault.svc.cluster.local,DNS:*.vault-internal,DNS:*.vault-internal.vault.svc.cluster.local,IP:127.0.0.1
CONF
    openssl x509 -req -in "$VSTATE/vault.csr" -CA "$VSTATE/vault.ca" -CAkey "$VSTATE/ca.key" -CAcreateserial -out "$VSTATE/vault.crt" -days 825 -sha256 -extfile "$VSTATE/extensions.cnf"
  fi
  "${K[@]}" -n vault create secret generic vault-ha-tls --from-file="vault.key=$VSTATE/vault.key" --from-file="vault.crt=$VSTATE/vault.crt" --from-file="vault.ca=$VSTATE/vault.ca" --dry-run=client -o json | "${K[@]}" apply -f -
  printf '%s' "$VAULT_LICENSE" > "$VSTATE/license"
  "${K[@]}" -n vault create secret generic vault-ent-license --from-file="license=$VSTATE/license" --dry-run=client -o json | "${K[@]}" apply -f -
  rm -f "$VSTATE/license"
  cp "$DEMO_ROOT/deploy/vault-values.yaml" "$VSTATE/values.yaml"
  helm repo add hashicorp https://helm.releases.hashicorp.com --force-update
  helm repo update hashicorp
  helm upgrade --install vault hashicorp/vault --version "${VAULT_HELM_VERSION:-0.34.1}" --kube-context workshop -n vault -f "$VSTATE/values.yaml" \
    --set-string "server.image.repository=$image_repo" --set-string "server.image.tag=$image_tag" --server-side=false
else
  helm --kube-context workshop -n vault status vault -o json > "$VSTATE/helm-status.json"
  if jq -e '.info.status=="failed"' "$VSTATE/helm-status.json" >/dev/null; then
    # Helm 4 SSA conflicts with the injector's self-managed caBundle.
    # Client-side apply preserves the current chart settings and injector CA.
    helm repo add hashicorp https://helm.releases.hashicorp.com --force-update
    helm upgrade vault hashicorp/vault --version "${VAULT_HELM_VERSION:-0.34.1}" --kube-context workshop -n vault --reuse-values --server-side=false
  fi
fi
# Helm can return before the StatefulSet controller creates the pods. Waiting
# only for Running fails immediately with NotFound on a clean installation.
# Wait separately: kubectl can also fail immediately when several named pods
# are missing, even with --for=create.
"${K[@]}" -n vault wait --for=create pod/vault-0 --timeout=450s
"${K[@]}" -n vault wait --for=create pod/vault-1 --timeout=450s
"${K[@]}" -n vault wait --for=create pod/vault-2 --timeout=450s
"${K[@]}" -n vault wait --for=jsonpath='{.status.phase}'=Running pod/vault-0 pod/vault-1 pod/vault-2 --timeout=450s
# start and verify always configure the xAI engine, whatever the initial provider.
if [ "${LUMEN_PREPARE_OPENAI:-0}" != 1 ]; then
  "${K[@]}" -n vault exec vault-0 -- test -x /vault/plugins/vault-plugin-secrets-xai || fail 'La imagen existente no incluye el plugin xAI; no se reemplaza automáticamente.'
fi
"${K[@]}" -n vault get secret vault-ha-tls -o json | jq -r '.data["vault.ca"]|@base64d' > "$VSTATE/vault.ca"
"${K[@]}" -n vault exec vault-0 -- vault status -format=json > "$VSTATE/status.json" || [ "$?" -eq 2 ]
if jq -e '.initialized==false' "$VSTATE/status.json" >/dev/null; then
  [ ! -s "$VSTATE/cluster-keys.json" ] || fail 'El cluster está vacío pero existen claves de otro despliegue. Usa otro LUMEN_STATE_DIR; no se sobrescriben.'
  "${K[@]}" -n vault exec vault-0 -- vault operator init -key-shares=1 -key-threshold=1 -format=json > "$VSTATE/cluster-keys.json"
fi
[ -s "$VSTATE/cluster-keys.json" ] || fail 'Vault ya está inicializado y faltan sus claves en el directorio de estado.'
for pod in vault-0 vault-1 vault-2; do
  for attempt in $(seq 1 30); do
    "${K[@]}" -n vault exec "$pod" -- vault status -format=json > "$VSTATE/status.json" || [ "$?" -eq 2 ]
    if jq -e '.initialized and (.sealed|not)' "$VSTATE/status.json" >/dev/null; then break; fi
    jq '{key:.unseal_keys_b64[0]}' "$VSTATE/cluster-keys.json" | "${K[@]}" -n vault exec -i "$pod" -- vault write -format=json sys/unseal - > "$VSTATE/unseal.json" 2>/dev/null || true
    sleep 2
  done
  "${K[@]}" -n vault exec "$pod" -- vault status -format=json | jq -e '.initialized and (.sealed|not)' >/dev/null
done
root_token=$(jq -er .root_token "$VSTATE/cluster-keys.json")
{
  printf 'VAULT_ADDR=%q\n' https://127.0.0.1:8443
  printf 'VAULT_CACERT=%q\n' "$VSTATE/vault.ca"
  printf 'VAULT_TOKEN=%q\n' "$root_token"
} > "$VAULT_ENV_FILE"
unset root_token
chmod 600 "$VAULT_ENV_FILE" "$VSTATE/cluster-keys.json"
start_forward vault vault pod/vault-0 8443 8200
load_vault
vault status -format=json | jq -e '.initialized and (.sealed|not)' >/dev/null
vault read -format=json sys/license/status | jq -e '.data.autoloaded.features | index("Agentic IAM")!=null and index("KMIP")!=null and index("Transform Secrets Engine")!=null' >/dev/null
# Preserve notebook compatibility; authoritative recovery state is outside /tmp.
[ ! -L /tmp/vault ] || fail '/tmp/vault es un enlace; no se copia la configuración de Vault'
mkdir -p /tmp/vault
[ "$(stat -f %u /tmp/vault)" = "$(id -u)" ] || fail '/tmp/vault pertenece a otro usuario; no se copia la configuración de Vault'
chmod 700 /tmp/vault
install -m 600 "$VAULT_ENV_FILE" /tmp/vault/config.env
echo 'Vault disponible, claves persistidas y licencia verificada.'
