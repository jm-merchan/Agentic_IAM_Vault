#!/usr/bin/env bash
# Public-only mirror. No Vault token or private signing material is read.
set -euo pipefail
umask 077
addr=${1:?}; ca=${2:?}; destination=${3:?}; issuer=${4:?}
mkdir -p "$destination/v1/verify/spiffe/.well-known"
directory="$destination/v1/verify/spiffe/.well-known"
refresh() {
  curl -fsS --connect-timeout 5 --max-time 15 --cacert "$ca" \
    "$addr/v1/verify/spiffe/.well-known/openid-configuration" > "$directory/discovery.next" || return 1
  jq -e --arg issuer "$issuer" '.issuer==$issuer and .jwks_uri==($issuer+"/.well-known/keys")' "$directory/discovery.next" >/dev/null || return 1
  curl -fsS --connect-timeout 5 --max-time 15 --cacert "$ca" \
    "$addr/v1/verify/spiffe/.well-known/keys" > "$directory/keys.next" || return 1
  jq -e '.keys|length>0 and all(.[];has("kid") and (has("d") or has("p") or has("q") or has("k")|not))' "$directory/keys.next" >/dev/null || return 1
  mv "$directory/discovery.next" "$directory/openid-configuration" || return 1
  mv "$directory/keys.next" "$directory/keys" || return 1
}
if [ "${5:-}" = --once ]; then refresh; exit; fi
while :; do
  if ! refresh; then
    # Remove stale public keys when Vault cannot be reached. No private material
    # is ever mirrored; ngrok will return 404 until the next successful refresh.
    rm -f "$directory/openid-configuration" "$directory/keys" "$directory/discovery.next" "$directory/keys.next"
    echo 'Public SPIFFE documents unavailable; retrying in 30 seconds.' >&2
  fi
  sleep 30
done
