#!/usr/bin/env bash
# Called only after verify.sh has completed successfully.
source "$(dirname "$0")/common.sh"
if [ -f "$MANUAL_RUN/installation.json" ]; then
 kubectl --context workshop get namespaces vault mysql lumen-observability -o json | jq '[.items[]|{name:.metadata.name,uid:.metadata.uid}]' > "$MANUAL_RUN/after.json"
 if [ -f "$MANUAL_RUN/before.json" ] && [ -f "$MANUAL_RUN/remove.json" ]; then
jq -n --slurpfile before "$MANUAL_RUN/before.json" --slurpfile after "$MANUAL_RUN/after.json" \
 --slurpfile install "$MANUAL_RUN/installation.json" --slurpfile tests "$MANUAL_RUN/workflows.json" \
 --slurpfile removed "$MANUAL_RUN/remove.json" --slurpfile users "$MANUAL_RUN/users.json" \
 --slurpfile final "$MANUAL_RUN/final-state.json" '
  ([$after[0][].name]|sort==["lumen-observability","mysql","vault"]) as $complete |
  ($complete and all($after[0][];.uid as $uid|all($before[0][];.uid!=$uid))) as $rebuilt |
  (($users[0].users|length)==3 and all($users[0].users[];.user_id as $id|
    all($removed[0].verify_resources[]|select(.kind=="user");.id!=$id))) as $new_users |
  {rebuilt_namespaces:$rebuilt,installation_passed:$install[0].all_passed,
   rebuilt_verify_users:$new_users,workflows_passed:$tests[0].all_passed,
   all_blocks_inactive:$final[0].all_blocks_inactive,
   all_passed:($rebuilt and $new_users and $install[0].all_passed and $tests[0].all_passed and $final[0].all_blocks_inactive)}' > "$MANUAL_RUN/result.json"
 else
  jq -n --slurpfile install "$MANUAL_RUN/installation.json" --slurpfile tests "$MANUAL_RUN/workflows.json" \
   --slurpfile final "$MANUAL_RUN/final-state.json" \
   '{installation_passed:$install[0].all_passed,workflows_passed:$tests[0].all_passed,
     all_blocks_inactive:$final[0].all_blocks_inactive,
     all_passed:($install[0].all_passed and $tests[0].all_passed and $final[0].all_blocks_inactive)}' > "$MANUAL_RUN/result.json"
 fi
else
 jq -n --slurpfile tests "$MANUAL_RUN/workflows.json" --slurpfile final "$MANUAL_RUN/final-state.json" \
  '{scope:"verification of existing installation",workflows_passed:$tests[0].all_passed,
    all_blocks_inactive:$final[0].all_blocks_inactive,
    all_passed:($tests[0].all_passed and $final[0].all_blocks_inactive)}' > "$MANUAL_RUN/result.json"
fi
jq -e '.all_passed' "$MANUAL_RUN/result.json" >/dev/null
printf '{"verification_pending":false,"all_passed":true}\n' > "$MANUAL_RUN/verification-state.json"
cat > "$MANUAL_RUN/README.md" <<MD
# Validación manual · $(date -u +%Y-%m-%dT%H:%M:%SZ)

[Guías](../../manual/README.md) · [Cómo repetir](../../manual/13-repeticion-script.md)

La verificación terminó con $(jq '.checks|length' "$MANUAL_RUN/workflows.json") comprobaciones funcionales. Los tres proveedores se seleccionan por sesión usando el catálogo conjunto. Las claves públicas del nuevo Vault deben haberse actualizado en el emisor Claude antes de esta fase.

- [Resultado conjunto](result.json) y [estado de verificación](verification-state.json).
- [Workflows](workflows.json): OIDC/OBO, datos protegidos, modelos, bloqueos y trazas.
- [Usuarios](users.json), [agentes](agents.json) y [estado final sin bloqueos](final-state.json).

Si esta ejecución incluye instalación o reconstrucción, sus informes installation.json, before.json, after.json y remove.json permanecen en este mismo directorio. El resultado solo afirma reconstrucción cuando se dispone de las evidencias de retirada e identidades anteriores y nuevas. Tokens, cookies y logs completos permanecen en el estado privado local. La prueba funcional no inspecciona visualmente la interfaz.
MD
printf 'Verificación terminada: %s/result.json\n' "$MANUAL_RUN"
