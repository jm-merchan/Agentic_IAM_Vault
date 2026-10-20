#!/usr/bin/env bash
# Tests apply the exact CLI policy blocks from chapter 12.
source "$(dirname "$0")/common.sh"
source "$MANUAL/session.sh"
source "$LUMEN_STATE_DIR/vault/config.env"
export VAULT_ADDR VAULT_CACERT VAULT_TOKEN VAULT_NAMESPACE=verify
case "$1:${2:-}" in
 xai:on) n=3;; xai:off) n=4;;
 database-read:on) n=5;; database-read:off) n=6;;
 database-write:on) n=7;; database-write:off) n=8;;
 decrypt:on) n=9;; decrypt:off) n=10;;
 cleanup-xai:) vault lease revoke -sync -prefix xai/creds/lumen/; exit;;
 *) exit 2;;
esac
source "$(block 12-bloqueos "$n")"
