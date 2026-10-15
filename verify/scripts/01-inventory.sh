#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
admin_login
api GET /v1.0/applications "$TMP_WORK/apps.json"
jq '[._embedded.applications[]|select(.name=="vault-authn-entry")|{name,application_id:(._links.self.href|split("/")[-1])}]' "$TMP_WORK/apps.json"
api GET /v1.0/auth-detail-types "$TMP_WORK/rar.json"
jq '{rar_types:[.authDetailTypes[]|.type]}' "$TMP_WORK/rar.json"
api GET /v1.0/sts/oauth/clients "$TMP_WORK/sts.json"
jq '{sts_clients:[.clients[]|{clientName,enabled}]}' "$TMP_WORK/sts.json"
app_token
jq '{iss,sub,aud,may_act_present:has("may_act")}' "$TMP_WORK/actor-claims.json"
echo 'Inventory and Client Credentials checks complete; no credentials printed.'
