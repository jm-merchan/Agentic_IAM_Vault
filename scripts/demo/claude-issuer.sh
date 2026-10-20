#!/usr/bin/env bash
# Synchronize the existing Claude issuer; no inference identity receives admin rights.
source "$(dirname "$0")/common.sh"
load_inputs
load_vault
export VAULT_NAMESPACE=verify
exec python3 "$DEMO_ROOT/scripts/demo/claude_issuer.py"
