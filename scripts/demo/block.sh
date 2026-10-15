#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
source "$DEMO_ROOT/chatbot/scripts/access-controls.sh"
operation=${1:?}; target=${2:-}
case "$operation" in block|unblock) block_paths "$target" >/dev/null;; blocks) ;; *) fail 'Operación inválida';; esac
load_inputs
load_vault
export VAULT_NAMESPACE=verify
if [ "$operation" = blocks ]; then
  for target in $(block_targets); do
    policy=$(vault policy read "lumen-block-$target") || fail 'Falta configurar los controles de bloqueo.'
    state=permitido
    [[ "$policy" != *'"deny"'* ]] || state=BLOQUEADO
    printf '%-18s %s\n' "$target" "$state"
  done
  echo 'Permitido significa sin bloqueo adicional; siguen aplicando los permisos del perfil y RAR.'
  exit 0
fi
agent=chatbot-oidc
[ "$target" != xai ] || agent=chatbot-xai
attachment="agent-registry/registration/display-name/$agent"
field=ceiling_policies
# Autonomous JWTs use entity policies. Ceilings constrain OBO delegations only.
if [ "$target" = xai ]; then attachment=identity/entity/name/chatbot-xai; field=policies; fi
vault read -format=json "$attachment" |
  jq -e --arg policy "lumen-block-$target" --arg field "$field" '.data[$field] | index($policy)!=null' >/dev/null ||
  fail 'El agente no tiene configuradas las políticas de bloqueo. Ejecuta la configuración de agentes primero.'
# Rotate the cache generation in Vault before lifting a block. This also works
# when no UI request occurred between block and unblock, across app instances.
if [ "$target" = xai ] && [ "$operation" = unblock ]; then
  openssl rand -hex 16 | jq -Rn '{generation:input}' | vault kv put -mount=secrets chatbot/xai-access - >/dev/null
fi
if [ "$operation" = block ]; then
  block_paths "$target" | while IFS= read -r path; do
    printf 'path "%s" { capabilities = ["deny"] }\n' "$path"
  done | vault policy write "lumen-block-$target" - >/dev/null
else
  printf '# Lumen: bloqueo inactivo. No concede permisos.\n' | vault policy write "lumen-block-$target" - >/dev/null
fi
if [ "$operation" = block ]; then
  case "$target" in
    xai|database-read|database-write)
      for path in $(block_paths "$target"); do
        [[ "$path" != secrets/* ]] || continue
        if ! vault lease revoke -sync -prefix "$path/" >/dev/null; then
          fail 'El deny permanece activo, pero no se han podido revocar todos los leases. Repite block; no se ha usado revoke-force.'
        fi
      done ;;
  esac
fi
vault policy read "lumen-block-$target"
printf '\n%s %s aplicado en Vault (namespace verify). No necesitas reiniciar Lumen ni iniciar sesión de nuevo.\n' "$operation" "$target"
[ "$target" != database-read ] || echo 'Afecta a RO y RW: las credenciales RW también permiten SELECT.'
