#!/usr/bin/env bash
# Add parameter support without changing OAuth clients, Vault ACLs or ceilings.
source "$(dirname "$0")/common.sh"
source "$VERIFY_DIR/scripts/rar-common.sh"
admin_login
configure_rar
