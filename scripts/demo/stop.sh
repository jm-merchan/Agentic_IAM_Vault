#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
load_inputs
fingerprint=$(printf '%s' "$LUMEN_STATE_DIR" | openssl dgst -sha256 | awk '{print substr($NF,1,12)}')
for file in "$LUMEN_STATE_DIR"/services/*.plist; do
  [ -f "$file" ] || continue
  label=$(plutil -extract Label raw "$file")
  [[ "$label" == local.lumen-demo."$fingerprint".* ]] || fail 'Etiqueta de servicio de otro despliegue; se conserva'
  launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
done
for file in "$LUMEN_STATE_DIR"/pids/*.pid; do
  [ -f "$file" ] || continue
  pid=$(cat "$file")
  [[ "$pid" =~ ^[0-9]+$ ]] || fail "PID no válido en $file"
  command=$(ps -p "$pid" -o command= 2>/dev/null || true)
  if [ -n "$command" ]; then
    owned=false
    name=$(basename "$file" .pid)
    case "$name" in
      lumen)
        cwd=$(lsof -a -p "$pid" -d cwd -Fn | sed -n 's/^n//p')
        if [[ "$command" == *python*'-m app.main'* && ( "$cwd" = "$DEMO_ROOT/chatbot" || "$cwd" = "$LUMEN_STATE_DIR/runtime/chatbot" ) ]]; then owned=true; fi;;
      vault|mysql|grafana|tempo|tempo-otlp|loki)
        case "$name" in
          vault) ns=vault; target=pod/vault-0; ports=8443:8200;;
          mysql) ns=mysql; target=svc/mysql-enterprise; ports=13306:3306;;
          grafana) ns=lumen-observability; target=svc/grafana; ports=3000:3000;;
          tempo) ns=lumen-observability; target=svc/tempo; ports=3200:3200;;
          tempo-otlp) ns=lumen-observability; target=svc/tempo; ports=4318:4318;;
          loki) ns=lumen-observability; target=svc/loki; ports=3100:3100;;
        esac
        if [[ "$command" == *kubectl*'--context workshop'*"-n $ns "*port-forward*"$target"*"$ports"* ]]; then owned=true; fi;;
    esac
    if [ "$owned" != true ]; then printf 'PID reutilizado por otro proceso: se conserva %s\n' "$pid"; continue; fi
    kill "$pid" 2>/dev/null || true
  fi
  rm "$file"
done
echo 'Procesos locales iniciados por demo.sh detenidos. Cluster, datos y recursos Verify conservados.'
