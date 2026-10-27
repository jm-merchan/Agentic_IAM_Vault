#!/usr/bin/env bash
# Called under demo.sh's deployment lock. No DELETE is sent in --dry-run.
source "$(dirname "$0")/common.sh"
load_inputs
dry_run=false
case "${1:-}" in '') ;; --dry-run) dry_run=true;; *) fail 'Uso: ./demo.sh remove [--dry-run]';; esac
[ "$#" -le 1 ] || fail 'Demasiados argumentos para remove'
for command in jq curl kubectl helm vault lsof plutil launchctl rg; do command -v "$command" >/dev/null || fail "Falta $command"; done
state=$(cd "$LUMEN_STATE_DIR" && pwd -P)
case "$state" in /|/tmp|/private/tmp|/Users|"$HOME"|"$DEMO_ROOT"|"$HOME/.local/state") fail 'LUMEN_STATE_DIR demasiado amplio para remove';; esac
case "$DEMO_ROOT/" in "$state/"*) fail 'El estado no puede contener el workspace';; esac
env_path=$(cd "$(dirname "$DEMO_ENV_FILE")" && pwd -P)/$(basename "$DEMO_ENV_FILE")
# oauth2c holds captures for the vault-chatbot-oidc callback; that app is deleted below.
STATE_FOLDERS=(vault mysql runtime vault-chatbot-storage services pids ngrok openai oauth2c claude contracts pdf-approval personal-spaces)
for folder in "${STATE_FOLDERS[@]}"; do
  case "$env_path" in "$state/$folder"|"$state/$folder/"*) fail '.env está dentro de un directorio que se retiraría';; esac
done
[ ! -d "$state/oauth2c/.lock" ] || fail 'Hay una celda oauth2c en marcha; termínala antes de retirar la demo.'
[ ! -L /tmp/lumen-telemetry ] || fail 'La ruta de telemetría es un enlace; no se sigue'
REMOVE_WORK=$(mktemp -d /tmp/lumen-remove.XXXXXX)
trap 'rm -rf "$REMOVE_WORK"' EXIT
source "$DEMO_ROOT/scripts/demo/remove-verify.sh"

# Build the entire plan before stopping services or deleting any resource.
"${K[@]}" get namespaces -o json > "$REMOVE_WORK/namespaces.json" || fail 'workshop no está accesible. Arranca el perfil existente con minikube start -p workshop antes de retirar sus recursos.'
"${K[@]}" get pv -o json > "$REMOVE_WORK/pv-all.json"
jq '[.items[]|select(.spec.claimRef.namespace=="vault" or .spec.claimRef.namespace=="mysql" or .spec.claimRef.namespace=="lumen-observability")|{name:.metadata.name,namespace:.spec.claimRef.namespace,reclaim_policy:.spec.persistentVolumeReclaimPolicy}]' "$REMOVE_WORK/pv-all.json" > "$REMOVE_WORK/volumes.json"
jq -e 'all(.[];.reclaim_policy=="Delete")' "$REMOVE_WORK/volumes.json" >/dev/null || fail 'Hay volúmenes con Retain: se requiere resolver su destino antes de un clean completo'
vault_sts=$("${K[@]}" -n vault get statefulset vault --ignore-not-found -o name)
legacy_keys=false
legacy_config=false
if [ "${LUMEN_LEGACY_VAULT_COMPAT:-1}" = 1 ]; then
if [ -f /tmp/vault/cluster-keys.json ] && [ -f "$state/vault/cluster-keys.json" ]; then
  jq -e --slurpfile current "$state/vault/cluster-keys.json" '.root_token==$current[0].root_token and .root_token!=null' /tmp/vault/cluster-keys.json >/dev/null || fail '/tmp/vault contiene claves de otro cluster; no se eliminan automáticamente'
  legacy_keys=true
fi
if [ -f /tmp/vault/config.env ] && [ -f "$VAULT_ENV_FILE" ] && cmp -s /tmp/vault/config.env "$VAULT_ENV_FILE"; then legacy_config=true; fi
else
  printf 'Compatibilidad legacy desactivada: /tmp/vault se conserva sin leer ni modificar.\n'
fi
remove_verify_login
remove_verify_inventory
jq -n --arg date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg tenant "$VERIFY_TENANT" --arg state "$state" --argjson dry_run "$dry_run" \
  --slurpfile targets "$REMOVE_WORK/targets.json" --slurpfile volumes "$REMOVE_WORK/volumes.json" \
  '{created_at:$date,dry_run:$dry_run,context:"workshop",namespaces:["mysql","lumen-observability","vault"],verify_tenant:$tenant,verify_resources:$targets[0],volumes:$volumes[0],local_state:$state,preserved:[".env","OpenAI project, service account and WIF provider/mapping","Claude issuer, federation rule and service account","Verify administrative API client","vault:path_access RAR schema","non-Lumen Verify resources","Minikube profile and image cache","workspace documentation and historical reports"]}' > "$LUMEN_STATE_DIR/remove-plan.json"
printf 'Retirada completa en workshop: namespaces mysql, lumen-observability y vault, TODO su contenido y PVC.\n'
printf 'Esto incluye todos los secretos/namespaces internos de este Vault y las filas de MySQL.\n'
jq -r '.[]|"  Volumen: \(.namespace)/\(.name)"' "$REMOVE_WORK/volumes.json"
printf 'Verify: %s\n' "$VERIFY_TENANT"
jq -r '.[]|"  \(.kind): \(.name) (\(.id))"' "$REMOVE_WORK/targets.json"
printf 'Estado operativo local: %s/{%s}\n' "$state" "$(IFS=,; echo "${STATE_FOLDERS[*]}")"
printf 'Se conservan .env, recursos WIF externos de OpenAI/Claude, cliente administrativo, RAR compartido, otros recursos Verify, perfil Minikube y documentación.\n'
printf 'Plan sin credenciales: %s/remove-plan.json\n' "$LUMEN_STATE_DIR"
if [ "$dry_run" = true ]; then echo 'Simulación: no se han detenido ni eliminado recursos.'; exit 0; fi

# Stop only this application's process, keeping the Vault tunnel for revocation.
fingerprint=$(printf '%s' "$LUMEN_STATE_DIR" | openssl dgst -sha256 | awk '{print substr($NF,1,12)}')
launchctl bootout "gui/$(id -u)/local.lumen-demo.$fingerprint.lumen" >/dev/null 2>&1 || true
pid=$(port_pid 8088 || true)
if [ -n "$pid" ]; then
  process=$(ps -p "$pid" -o command=)
  cwd=$(lsof -a -p "$pid" -d cwd -Fn | sed -n 's/^n//p')
  [[ "$process" == *python*'-m app.main'* && ( "$cwd" = "$DEMO_ROOT/chatbot" || "$cwd" = "$state/runtime/chatbot" ) ]] || fail 'El puerto 8088 pertenece a otra aplicación; se conserva'
  kill "$pid"
  for attempt in $(seq 1 30); do [ -n "$(port_pid 8088 || true)" ] || break; sleep 1; done
  [ -z "$(port_pid 8088 || true)" ] || fail 'Lumen no se ha detenido'
fi

# Revoke externally issued xAI keys before destroying their lease store.
# An uninitialized Vault cannot have issued keys. A sealed initialized Vault
# must be resumed first; never hide revocation failures with revoke-force.
if [ -n "$vault_sts" ]; then
  "${K[@]}" -n vault exec vault-0 -- vault status -format=json > "$REMOVE_WORK/vault-status.json" || [ "$?" -eq 2 ]
  if jq -e .initialized "$REMOVE_WORK/vault-status.json" >/dev/null; then
    jq -e '.sealed|not' "$REMOVE_WORK/vault-status.json" >/dev/null || fail 'Desella Vault antes de remove para revocar las claves xAI pendientes'
    load_vault
    start_forward vault vault pod/vault-0 8443 8200
    if vault namespace lookup -format=json verify > "$REMOVE_WORK/namespace.json" 2> "$REMOVE_WORK/namespace.err"; then
        export VAULT_NAMESPACE=verify
        vault secrets list -format=json > "$REMOVE_WORK/mounts.json"
        if jq -e 'has("xai/")' "$REMOVE_WORK/mounts.json" >/dev/null; then
          vault lease revoke -sync -prefix xai/creds/lumen/ >/dev/null
          echo 'Leases xAI de Lumen revocados antes de eliminar Vault.'
        fi
        unset VAULT_NAMESPACE
    elif ! rg -qx 'Namespace not found' "$REMOVE_WORK/namespace.err"; then
      cat "$REMOVE_WORK/namespace.err" >&2
      fail 'No se pudo comprobar verify en Vault; se conserva el estado'
    fi # An absent verify namespace is valid for an interrupted installation.
  fi
fi
remove_verify_apply
bash "$DEMO_ROOT/scripts/demo/stop.sh"
# Keep Vault/KMIP available until MySQL has stopped.
"${K[@]}" delete namespace mysql lumen-observability --ignore-not-found --wait=true --timeout=300s
helm --kube-context workshop -n vault uninstall vault --ignore-not-found --cascade foreground --wait --timeout 300s
"${K[@]}" delete namespace vault --ignore-not-found --wait=true --timeout=300s
while IFS= read -r volume; do
  if [ -n "$("${K[@]}" get pv "$volume" --ignore-not-found -o name)" ]; then
    "${K[@]}" wait --for=delete "pv/$volume" --timeout=300s
  fi
done < <(jq -r '.[].name' "$REMOVE_WORK/volumes.json")
[ -z "$("${K[@]}" get namespace vault mysql lumen-observability --ignore-not-found -o name)" ] || fail 'Quedan namespaces del laboratorio'

# Do not discard recovery keys until remote removal and PVC deletion succeeded.
if [ "$legacy_keys" = true ]; then
  for file in cluster-keys.json vault.key vault.ca vault.crt vault.csr; do rm -f "/tmp/vault/$file"; done
fi
if [ "$legacy_config" = true ]; then rm /tmp/vault/config.env; fi
for folder in "${STATE_FOLDERS[@]}"; do rm -rf "${state:?}/$folder"; done
# This fixed path belongs to the lab's local span exporter; historical screenshots
# and the source notebooks are preserved in the workspace.
rm -f /tmp/lumen-telemetry/spans.jsonl
rmdir /tmp/lumen-telemetry 2>/dev/null || true
jq --arg date "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '.+{completed:true,removed_at:$date}' "$LUMEN_STATE_DIR/remove-plan.json" > "$LUMEN_STATE_DIR/last-remove.json"
echo 'Retirada completada. Para crear Vault y la demo desde cero: ./demo.sh start'
