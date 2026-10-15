#!/usr/bin/env bash
# Known synthetic data lets every profile test decrypt/decode, even with no rows.
source "$(dirname "$0")/../../verify/scripts/common.sh"
kv_read chatbot/runtime > "$TMP_WORK/runtime.json"
if jq -e '.permission_probe | .version==1 and
  (.profile_ciphertext|type=="string" and startswith("vault:v")) and
  (.profile_plaintext|type=="string" and length>0) and
  (.dni.value|type=="string" and length>0) and (.dni.token|type=="string" and length>0) and
  (.iban.value|type=="string" and length>0) and (.iban.token|type=="string" and length>0)' \
  "$TMP_WORK/runtime.json" >/dev/null; then
  echo 'Datos ficticios de comprobación ya preparados.'
  exit 0
fi
jq -n '{version:1,profile_plaintext:("lumen-permission-probe"|@base64),
  dni:{value:"lumen-probe-dni"},iban:{value:"lumen-probe-iban"}}' > "$TMP_WORK/probe.json"
jq '{plaintext:.profile_plaintext}' "$TMP_WORK/probe.json" |
  vault write -format=json transit/encrypt/lumen-applications - > "$TMP_WORK/encrypted.json"
jq --slurpfile result "$TMP_WORK/encrypted.json" '.profile_ciphertext=$result[0].data.ciphertext' \
  "$TMP_WORK/probe.json" > "$TMP_WORK/next.json"
mv "$TMP_WORK/next.json" "$TMP_WORK/probe.json"
for field in dni iban; do
  jq --arg field "$field" '{value:.[$field].value,transformation:("lumen-"+$field)}' "$TMP_WORK/probe.json" |
    vault write -format=json "transform/encode/lumen-$field" - > "$TMP_WORK/encoded.json"
  jq --arg field "$field" --slurpfile result "$TMP_WORK/encoded.json" '.[$field].token=$result[0].data.encoded_value' \
    "$TMP_WORK/probe.json" > "$TMP_WORK/next.json"
  mv "$TMP_WORK/next.json" "$TMP_WORK/probe.json"
done
jq --slurpfile probe "$TMP_WORK/probe.json" '.permission_probe=$probe[0]' "$TMP_WORK/runtime.json" |
  kv_write chatbot/runtime
echo 'Datos ficticios preparados para comprobar Transit/Transform mediante OBO.'
