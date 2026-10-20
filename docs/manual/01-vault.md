# 01 · Desplegar e inicializar Vault

[Índice](README.md) · Requiere [00](00-entorno.md) · Siguiente: [MySQL](02-mysql.md)

## 1. Arrancar Minikube

```bash
source "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/manual/session.sh"
if minikube status -p workshop -o json > "$MANUAL/minikube-status.json" 2>/dev/null &&
   jq -e '.Host=="Running" and .APIServer=="Running"' "$MANUAL/minikube-status.json" >/dev/null; then
  printf 'El perfil workshop ya está arrancado.\n'
else
  minikube start -p workshop --driver="${MINIKUBE_DRIVER:-podman}" \
    --memory="${MINIKUBE_MEMORY:-8192}" --cpus="${MINIKUBE_CPUS:-4}"
fi
"${K[@]}" get nodes -o wide
node_epoch=$(minikube ssh -p workshop -- date -u +%s </dev/null | tr -d '\r\n')
skew=$(( $(date -u +%s) - node_epoch ))
if [ "$skew" -gt 5 ] || [ "$skew" -lt -5 ]; then
  if [ "${CONTAINER_ENGINE:-podman}" != podman ]; then
    printf 'Sincroniza el reloj de la VM de contenedores antes de continuar (desfase %s s).\n' "$skew" >&2
    exit 1
  fi
  podman machine ssh "${PODMAN_MACHINE:-podman-machine-default}" \
    sudo -n date -u -s "@$(date -u +%s)" </dev/null
  # Reiniciar el NTP activo para descartar ajustes pendientes del reloj anterior.
  podman machine ssh "${PODMAN_MACHINE:-podman-machine-default}" \
    'if systemctl is-active --quiet chronyd; then sudo -n systemctl restart chronyd; fi' </dev/null
  node_epoch=$(minikube ssh -p workshop -- date -u +%s </dev/null | tr -d '\r\n')
  skew=$(( $(date -u +%s) - node_epoch ))
fi
[ "$skew" -le 5 ] && [ "$skew" -ge -5 ]
```

Un perfil existente conserva sus CPU/memoria; `minikube start` no lo redimensiona. La comprobación evita reinicios y descargas innecesarias cuando ya está disponible. Si el Mac estuvo suspendido, el paso sincroniza la VM Podman cuando el desfase supera 5 segundos y reinicia `chronyd` si estaba activo. El umbral es inferior a los 15 segundos de tolerancia del perfil OAuth; comprobar solo 60 segundos permitía pasar un entorno que rechazaba JWT recién emitidos. `PODMAN_MACHINE` permite seleccionar otra VM de Podman. Repetir este paso antes de probar OIDC/OBO si hubo una pausa o suspensión.

Para sincronizar explícitamente la VM Podman de esta demo y después repetir la comprobación:

```bash
podman machine ssh podman-machine-default sudo -n date -u -s "@$(date -u +%s)" </dev/null
podman machine ssh podman-machine-default \
  'if systemctl is-active --quiet chronyd; then sudo -n systemctl restart chronyd; fi' </dev/null
```

## 2. Crear TLS y los secretos Kubernetes

Este paso corresponde a un despliegue nuevo. Si ya existe `vault-ha-tls`, conservar su CA/certificado y las claves de recuperación del clúster; no generar otros encima.

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

## 3. Instalar Vault Enterprise con Raft

[deploy/vault-values.yaml](../../deploy/vault-values.yaml) define tres réplicas Raft, TLS, `retry_join`, plugin directory, almacenamiento persistente y UI. Injector y CSI están desactivados. Revisar y aplicar ese manifiesto:

```bash
cat deploy/vault-values.yaml
helm repo add hashicorp https://helm.releases.hashicorp.com --force-update
helm repo update hashicorp
helm upgrade --install vault hashicorp/vault --version "${VAULT_HELM_VERSION:-0.34.1}" \
  --kube-context workshop -n vault -f deploy/vault-values.yaml \
  --set-string server.image.repository=josemerchan/vault-xai \
  --set-string server.image.tag=2.1.2-ent --server-side=false
"${K[@]}" -n vault wait --for=create pod/vault-0 --timeout=450s
"${K[@]}" -n vault wait --for=create pod/vault-1 --timeout=450s
"${K[@]}" -n vault wait --for=create pod/vault-2 --timeout=450s
"${K[@]}" -n vault wait --for=jsonpath='{.status.phase}'=Running \
  pod/vault-0 pod/vault-1 pod/vault-2 --timeout=450s
```

Helm puede terminar antes de que el controlador cree los pods. Primero se espera
a que exista cada pod por separado y después a que los tres estén en `Running`.
`Running` no significa inicializado o unsealed. Se usa `--server-side=false` por compatibilidad con Helm 4 en esta demo.

## 4. Inicializar una sola vez y hacer unseal

La respuesta de init contiene el root token y la clave de unseal. El esquema 1/1 simplifica este laboratorio.

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

`vault write sys/unseal -` es el equivalente CLI que permite enviar la clave por stdin. Los seguidores se unen mediante `retry_join`. Si ya estaba inicializado y no tienes sus claves, recupera el bootstrap correcto; no vuelvas a inicializar ni borres sus PVC.

## 5. Conectar Vault CLI desde el Mac

En una **segunda terminal** mantener activo este port-forward; no arrancar otro si el puerto ya está gestionado por `demo.sh`:

```bash
kubectl --context workshop -n vault port-forward --address 127.0.0.1 pod/vault-0 8443:8200
```

En la terminal de configuración:

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

Resultado: tres peers, Vault unsealed y funciones Agentic IAM/KMIP/Transform disponibles. UI: `https://127.0.0.1:8443/ui/`; confiar en la CA de laboratorio y usar Token como método de acceso. Para copiar el token en macOS sin imprimirlo: `printf '%s' "$VAULT_TOKEN" | pbcopy`.

## 6. Namespace y secretos de aprovisionamiento

Comprobar `vault namespace list` y `vault secrets list` antes de habilitar recursos existentes. En una instalación nueva:

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

El nombre CLI `secrets/verify-admin` corresponde a la ruta API/ACL `secrets/data/verify-admin`, porque el motor es KV v2. No son dos secretos distintos.

Fuentes locales: [vault.sh](../../scripts/demo/vault.sh), [bootstrap.sh](../../scripts/demo/bootstrap.sh).
