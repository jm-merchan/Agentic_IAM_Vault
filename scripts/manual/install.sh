#!/usr/bin/env bash
# Execute the documented Bash blocks in order. Does not call demo.sh start.
source "$(dirname "$0")/common.sh"
trap 'printf "Fallo en la instalación manual; consultar %s/logs\n" "$MANUAL" >&2' ERR
[ -f .env ] || { echo 'Completa .env antes de instalar' >&2; exit 1; }
set -a
source .env
set +a
require_model_inputs
[ -z "$(kubectl --context workshop get namespace vault mysql lumen-observability --ignore-not-found -o name)" ] || { echo 'Se requiere un despliegue vacío; usa rehearse.sh rebuild' >&2; exit 1; }
: > "$MANUAL/steps.jsonl"
: > "$MANUAL/background-blocks.jsonl"
step 00-entorno 2
step 00-entorno 3
step 01-vault 1
for n in 3 4 5; do step 01-vault "$n"; done
background 01-vault 6 vault
wait_port 8443
step 01-vault 7
for n in 2 3 4; do step 09-observabilidad "$n"; done
step 01-vault 8
for n in 1 2 3 4 5 6 7 8 9; do step 02-mysql "$n"; done
background 02-mysql 10 mysql
wait_port 13306
# Verify: session, admin token, RAR and application inventory.
for n in $(seq 1 18); do step 03-verify "$n"; done
for suffix in oidc research; do
 for n in $(seq 19 29); do step 03-verify "$n"; done
done
unset suffix
# STS, then users and groups, then the shared directory.
for n in $(seq 30 39); do step 03-verify "$n"; done
for ROLE in reader writer supervisor; do
 for n in $(seq 40 54); do step 03-verify "$n"; done
done
unset ROLE
for n in $(seq 55 57); do step 03-verify "$n"; done
for n in $(seq 1 9); do step 04-vault-iam "$n"; done
# The manual selects suffix in block 10; the rehearsal supplies both values.
for suffix in oidc research; do
 for n in $(seq 11 21); do step 04-vault-iam "$n"; done
done
unset suffix
for n in $(seq 22 25); do step 04-vault-iam "$n"; done
for n in $(seq 1 6); do step 05-proteccion "$n"; done
step 14-agentes-por-tarea 1
step 01-vault 1
for n in $(seq 4 7); do step 03-verify "$n"; done
for n in $(seq 1 10); do step 06-xai "$n"; done
step 01-vault 1
for n in $(seq 4 7); do step 03-verify "$n"; done
: "${OPENAI_PROJECT_ID:?Prepara el proyecto OpenAI según 07}"
: "${OPENAI_SERVICE_ACCOUNT_ID:?Prepara la cuenta OpenAI según 07}"
: "${OPENAI_IDENTITY_PROVIDER_ID:?Prepara el mapping WIF según 07}"
for n in 1 2 3 4; do step 07-openai-spiffe "$n"; done
printf 'publisher\t%s\t%s\n' "$PUBLISHER_PID" "$MANUAL/publish-public.sh" >> "$MANUAL/processes.tsv"
background 07-openai-spiffe 5 ngrok
# Public tunnel readiness is asynchronous; retry reads, never repeat provisioning.
for retry in $(seq 1 60); do
 if curl -fsS "$SPIFFE_ISSUER/.well-known/openid-configuration" > "$MANUAL/ngrok-ready.json" 2>/dev/null && jq -e --arg issuer "$SPIFFE_ISSUER" '.issuer==$issuer' "$MANUAL/ngrok-ready.json" >/dev/null; then break; fi
 sleep 2
done
for n in 6 7 9 11 12 13 14 15 16; do step 07-openai-spiffe "$n"; done
step 01-vault 1
for n in $(seq 4 7); do step 03-verify "$n"; done
for n in 1 2 3 4 5 6 7; do step 08-claude-spiffe "$n"; done
vault read -format=json spiffe/.well-known/keys | jq '.data.keys' > "$MANUAL_RUN/claude-jwks.json"
bash "$MANUAL_ROOT/scripts/demo/claude-issuer.sh"
for n in 5 6 7; do step 09-observabilidad "$n"; done
background 09-observabilidad 8 grafana
background 09-observabilidad 9 tempo
background 09-observabilidad 10 loki
for port in 3000 3200 4318 3100; do wait_port "$port"; done
step 09-observabilidad 11
for n in 1 2; do step 10-aplicacion "$n"; done
if [ ! -x /tmp/vault-chatbot-venv/bin/python ]; then
 step 10-aplicacion 3
else
 uv pip install --python /tmp/vault-chatbot-venv/bin/python -r chatbot/requirements.lock.txt > "$MANUAL/logs/runtime-dependencies.log" 2>&1
fi
# Personal spaces require the Python environment and the synchronized users.
step 16-espacios-personales 1
step 17-contratacion-ciba 1
background 10-aplicacion 4 lumen
wait_port 8088
for retry in $(seq 1 30); do
 if curl -fsS http://localhost:8088/health > "$MANUAL/health.json" 2>/dev/null && jq -e '.status=="ok" and ([.models[].provider]|sort)==["anthropic","openai","xai"]' "$MANUAL/health.json" >/dev/null; then break; fi
 sleep 1
done
jq -e '.status=="ok" and ([.models[].provider]|sort)==["anthropic","openai","xai"]' "$MANUAL/health.json" >/dev/null
jq -n --slurpfile steps "$MANUAL/steps.jsonl" --slurpfile background "$MANUAL/background-blocks.jsonl" \
 '{steps:$steps,background_blocks:$background,services_ready:true,verification_pending:true,all_passed:all($steps[];.passed)}' > "$MANUAL_RUN/installation.json"
cp "$MANUAL/health.json" "$MANUAL_RUN/health.json"
printf 'Instalación local configurada. En modo console, actualiza las JWKS exportadas en Claude. Ejecuta verify para comprobar el recorrido: %s\n' "$MANUAL_RUN"
