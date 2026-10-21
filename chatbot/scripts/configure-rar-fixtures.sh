#!/usr/bin/env bash
# Two synthetic ciphertexts let the UI prove that a token can decrypt only one.
source "$(dirname "$0")/../../verify/scripts/common.sh"
kv_read chatbot/runtime > "$TMP_WORK/runtime.json"
if jq -e '.rar_probe | .version==1 and
  (.approved.ciphertext|type=="string" and startswith("vault:v")) and
  (.other.ciphertext|type=="string" and startswith("vault:v")) and
  (.approved.plaintext|type=="string" and length>0) and
  (.other.plaintext|type=="string" and length>0)' "$TMP_WORK/runtime.json" >/dev/null; then
  echo 'Datos ficticios RAR existentes conservados.'
  exit 0
fi
printf '{"version":1}' > "$TMP_WORK/rar-probe.json"
for sample in approved other; do
  jq -n --arg text "lumen-rar-$sample-synthetic-profile" '{plaintext:($text|@base64)}' > "$TMP_WORK/plain.json"
  vault write -format=json transit/encrypt/lumen-applications - < "$TMP_WORK/plain.json" > "$TMP_WORK/encrypted.json"
  jq --arg sample "$sample" --slurpfile plain "$TMP_WORK/plain.json" --slurpfile encrypted "$TMP_WORK/encrypted.json" \
    '.[$sample]={plaintext:$plain[0].plaintext,ciphertext:$encrypted[0].data.ciphertext}' "$TMP_WORK/rar-probe.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/rar-probe.json"
done
jq --slurpfile fixture "$TMP_WORK/rar-probe.json" '.rar_probe=$fixture[0]' "$TMP_WORK/runtime.json" | kv_write chatbot/runtime
echo 'Dos perfiles ficticios preparados para comparar RAR; políticas y solicitudes conservadas.'
