#!/usr/bin/env bash
# Invoked through guided-run.sh so every command has its own complete environment.
source "$(dirname "$0")/../../verify/scripts/common.sh"
case "${1:-}" in
  bootstrap)
    vault policy write chatbot-bootstrap - < "$VERIFY_DIR/../chatbot/policies/bootstrap.hcl" >/dev/null
    echo 'Política chatbot-bootstrap aplicada desde el archivo del repositorio.'
    ;;
  check)
    for role in reader writer supervisor; do
      group="chatbot-${role}s"
      vault read -format=json "identity/group/name/$group" > "$TMP_WORK/group.json"
      jq -e --arg name "$group" --arg policy "chatbot-$role" \
        '.data.name==$name and .data.type=="internal" and (.data.policies==[$policy]) and (.data.member_entity_ids|type=="array")' \
        "$TMP_WORK/group.json" >/dev/null || fail "El grupo $group no tiene la configuración esperada."
      jq '.data|{name,type,policies,member_count:(.member_entity_ids|length)}' "$TMP_WORK/group.json"
    done
    vault policy read chatbot-bootstrap > "$TMP_WORK/bootstrap.hcl"
    cmp -s "$TMP_WORK/bootstrap.hcl" "$VERIFY_DIR/../chatbot/policies/bootstrap.hcl" ||
      fail 'La política bootstrap difiere del archivo del repositorio; ejecuta el paso 6 de 04-vault-iam.md.'
    echo 'Grupos y política bootstrap comprobados en Vault.'
    ;;
  *) fail 'Uso: iam.sh bootstrap|check';;
esac
