#!/usr/bin/env bash
# Single entry point. Configuration lives in .env; generated state is local/private.
source "$(dirname "$0")/scripts/demo/common.sh"
action=${1:-start}
[ "$#" -eq 0 ] || shift
case "$action" in up) action=start;; esac
case "$action" in
  check|status|stop) [ "$#" -eq 0 ] || fail 'Argumentos inesperados'; exec bash "$DEMO_ROOT/scripts/demo/$action.sh" ;;
  start|verify|prepare-openai)
    if [ "$#" -ne 0 ]; then
      [ "$#" -eq 2 ] && [ "$1" = --provider ] || fail 'Uso: ./demo.sh start|verify [--provider auto|xai|openai|anthropic]'
      export LUMEN_PROVIDER_OVERRIDE=$2
      shift 2
    fi
    if [ "$action" = prepare-openai ]; then export LUMEN_PROVIDER_OVERRIDE=openai LUMEN_PREPARE_OPENAI=1; fi;;
  block|unblock) [ "$#" -eq 1 ] || fail 'Uso: ./demo.sh block|unblock xai|database-read|database-write|decrypt';
    case "$1" in xai|database-read|database-write|decrypt) ;; *) fail 'Recurso de bloqueo inválido';; esac ;;
  blocks) [ "$#" -eq 0 ] || fail 'Uso: ./demo.sh blocks'; exec bash "$DEMO_ROOT/scripts/demo/block.sh" blocks ;;
  remove) [ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && [ "$1" = --dry-run ]; } || fail 'Uso: ./demo.sh remove [--dry-run]';;
  -h|--help) printf 'Uso: ./demo.sh start|verify [--provider auto|xai|openai|anthropic]\n     ./demo.sh prepare-openai\n     ./demo.sh check|status|stop|remove [--dry-run]|blocks\n     ./demo.sh block|unblock xai|database-read|database-write|decrypt\nremove elimina datos y recursos locales/Verify; start los recrea desde .env.\n'; exit 0;;
  *) printf 'Uso: ./demo.sh [start|up|check|status|verify|stop|remove [--dry-run]|blocks]\n     ./demo.sh block|unblock xai|database-read|database-write|decrypt\n'; exit 2 ;;
esac
load_inputs
case "$action" in start|verify|prepare-openai) source "$DEMO_ROOT/scripts/demo/model-provider.sh";; esac
lock="$LUMEN_STATE_DIR/deploy.lock"
if ! mkdir "$lock" 2>/dev/null; then
  owner=$(cat "$lock/pid" 2>/dev/null || true)
  if [[ "$owner" =~ ^[0-9]+$ ]] && kill -0 "$owner" 2>/dev/null; then fail 'Ya hay otra ejecución de demo.sh en curso.'; fi
  rm -f "$lock/pid"
  rmdir "$lock"
  mkdir "$lock"
fi
printf '%s\n' "$$" > "$lock/pid"
finish() {
  local status=$?
  if [ -n "${report:-}" ] && [ -f "$report" ]; then
    mkdir -p "$LUMEN_STATE_DIR/reports"
    cp "$report" "$LUMEN_STATE_DIR/reports/$run_id-$action.json"
  fi
  rm -f "$lock/pid"
  rmdir "$lock"
  exit "$status"
}
trap finish EXIT
run_id=$(date -u +%Y%m%dT%H%M%SZ)
run_log="$LUMEN_STATE_DIR/logs/deploy-$run_id.log"
report="$LUMEN_STATE_DIR/last-run.json"
jq -n --arg run "$run_id" --arg action "$action" --argjson dry_run "$([ "${1:-}" = --dry-run ] && echo true || echo false)" '{run:$run,action:$action,dry_run:$dry_run,completed:false,steps:[]}' > "$report"
step() {
  local name=$1; shift
  printf '→ %s\n' "$name"
  if "$@" >> "$run_log" 2>&1; then
    jq --arg name "$name" '.steps += [{name:$name,passed:true}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    printf '  OK\n'
  else
    jq --arg name "$name" '.steps += [{name:$name,passed:false}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    printf '  Fallo. Log privado: %s\n' "$run_log" >&2
    exit 1
  fi
}
if [ "$action" = block ] || [ "$action" = unblock ]; then
  bash "$DEMO_ROOT/scripts/demo/block.sh" "$action" "$@"
  jq '.completed=true | .steps=[{name:"Control de acceso en Vault",passed:true}]' "$report" > "$report.next"
  mv "$report.next" "$report"
  exit 0
fi
if [ "$action" = remove ]; then
  if bash "$DEMO_ROOT/scripts/demo/remove.sh" "$@" 2>&1 | tee -a "$run_log"; then
    jq '.completed=true | .steps=[{name:"Retirada de la demo (o simulación)",passed:true}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    exit 0
  else
    jq '.steps=[{name:"Retirada de la demo",passed:false}]' "$report" > "$report.next"
    mv "$report.next" "$report"
    printf 'Retirada interrumpida. Log privado: %s\n' "$run_log" >&2
    exit 1
  fi
fi
if [ "$action" = prepare-openai ]; then
  step 'Prerrequisitos OpenAI y .env' bash "$DEMO_ROOT/scripts/demo/check.sh"
  step 'Minikube y Vault' bash "$DEMO_ROOT/scripts/demo/vault.sh"
  step 'Namespace verify y secretos de integración' bash "$DEMO_ROOT/scripts/demo/bootstrap.sh"
  step 'Vault SPIFFE JWT-SVID' bash "$DEMO_ROOT/scripts/demo/spiffe.sh"
  step 'Discovery y JWKS públicos mediante ngrok' bash "$DEMO_ROOT/scripts/demo/ngrok.sh"
  step 'Proyecto y cuenta de servicio OpenAI' bash "$DEMO_ROOT/scripts/demo/openai-admin.sh"
  jq '.completed=true' "$report" > "$report.next"; mv "$report.next" "$report"
  printf '\nEmisor preparado. Crea el proveedor/mapping según docs/OPENAI_SPIFFE.md y guarda OPENAI_IDENTITY_PROVIDER_ID en .env. Después: ./demo.sh start --provider openai\n'
  exit 0
fi
if [ "$action" = start ]; then
  select_model_provider
  step 'Prerrequisitos y .env' bash "$DEMO_ROOT/scripts/demo/check.sh"
  step 'Minikube, Vault, TLS, init/unseal y plugin' bash "$DEMO_ROOT/scripts/demo/vault.sh"
  step 'MySQL Enterprise y KMIP' bash "$DEMO_ROOT/scripts/demo/mysql.sh"
  step 'Namespace verify y secretos de integración' bash "$DEMO_ROOT/scripts/demo/bootstrap.sh"
  step 'RAR y perfil OAuth de Vault' bash "$DEMO_ROOT/verify/scripts/configure-base.sh"
  step 'Entorno Python' bash "$DEMO_ROOT/chatbot/scripts/install.sh"
  step 'Roles MySQL RO/RW y catálogo' bash "$DEMO_ROOT/chatbot/scripts/01-database.sh"
  step 'Clientes OIDC, Tavily y STS en Verify' bash "$DEMO_ROOT/chatbot/scripts/02-verify-apps.sh"
  step 'Tres usuarios y grupos' bash "$DEMO_ROOT/chatbot/scripts/03-verify-users.sh"
  step 'Transit, tokenización y solicitudes' bash "$DEMO_ROOT/chatbot/scripts/06-data-protection.sh"
  step 'Políticas, entidades y agentes registrados' bash "$DEMO_ROOT/chatbot/scripts/04-vault-agents.sh"
  step 'Agentes opcionales por tarea' bash "$DEMO_ROOT/chatbot/scripts/configure-task-agents.sh"
  step 'Asignaciones OIDC y grupos de Vault' bash "$DEMO_ROOT/chatbot/scripts/05-sync-groups.sh"
  step 'Espacios personales opcionales' bash "$DEMO_ROOT/chatbot/scripts/configure-personal-spaces.sh"
  step 'Motor dinámico xAI' bash "$DEMO_ROOT/scripts/demo/xai.sh"
  step 'Identidad xAI' bash "$DEMO_ROOT/chatbot/scripts/configure-xai.sh"
  step 'Vault SPIFFE JWT-SVID para OpenAI' env LUMEN_SELECTED_PROVIDER=openai bash "$DEMO_ROOT/scripts/demo/spiffe.sh"
  step 'Vault SPIFFE JWT-SVID para Claude' env LUMEN_SELECTED_PROVIDER=anthropic bash "$DEMO_ROOT/scripts/demo/spiffe.sh"
  step 'Discovery y JWKS públicos mediante ngrok' bash "$DEMO_ROOT/scripts/demo/ngrok.sh"
  step 'Sincronizar claves públicas del emisor Claude' bash "$DEMO_ROOT/scripts/demo/claude-issuer.sh"
  step 'Proyecto y cuenta de servicio OpenAI' bash "$DEMO_ROOT/scripts/demo/openai-admin.sh"
  load_inputs
  step 'Identidad OpenAI' bash "$DEMO_ROOT/chatbot/scripts/configure-openai.sh"
  step 'Identidad Claude' bash "$DEMO_ROOT/chatbot/scripts/configure-anthropic.sh"
  step 'Catálogo de proveedores para el selector' bash "$DEMO_ROOT/chatbot/scripts/configure-models.sh"
  step 'Auditoría correlacionada de Vault' bash "$DEMO_ROOT/chatbot/scripts/enable-audit.sh"
  step 'Grafana, Loki, Tempo y Alloy' bash "$DEMO_ROOT/chatbot/scripts/deploy-observability.sh"
  step 'Puertos locales y Lumen' bash "$DEMO_ROOT/scripts/demo/start.sh"
  step 'Claude: federación SPIFFE e inferencia real' bash "$DEMO_ROOT/chatbot/scripts/verify-anthropic.sh"
fi
step 'Persistencia del runtime y aislamiento de secretos' bash "$DEMO_ROOT/scripts/demo/verify-runtime.sh"
step 'Pruebas de aplicación' bash -c 'cd "$DEMO_ROOT/chatbot"; /tmp/vault-chatbot-venv/bin/python -m pytest -q tests'
step 'MySQL, permisos del agente y búsqueda Tavily' bash "$DEMO_ROOT/chatbot/scripts/test-infrastructure.sh"
step 'Estado final de servicios' bash "$DEMO_ROOT/scripts/demo/status.sh"
if [ "$action" = verify ]; then
  select_model_provider
  if [ "$LUMEN_SELECTED_PROVIDER" = xai ]; then
    step 'xAI: inferencia, denegaciones y caducidad real' bash "$DEMO_ROOT/chatbot/scripts/verify-xai.sh"
  elif [ "$LUMEN_SELECTED_PROVIDER" = openai ]; then
    step 'OpenAI: SPIFFE JWT-SVID, token exchange e inferencia' bash "$DEMO_ROOT/chatbot/scripts/verify-openai.sh"
  else
    step 'Claude: SPIFFE JWT-SVID, token RFC 7523 e inferencia' bash "$DEMO_ROOT/chatbot/scripts/verify-anthropic.sh"
  fi
fi
jq '.completed=true' "$report" > "$report.next"
mv "$report.next" "$report"
printf '\nDemo lista: http://localhost:8088\nGrafana: http://localhost:3000/d/lumen-iam\nInforme: %s\n' "$report"
