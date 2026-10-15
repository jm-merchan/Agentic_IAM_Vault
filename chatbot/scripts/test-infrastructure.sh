#!/usr/bin/env bash
source "$(dirname "$0")/../../verify/scripts/common.sh"
CHATBOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
# A failed run must not leave an older passing report presented as current.
rm -f "$CHATBOT_DIR/docs/infrastructure-tests.json"
for role in readonly readwrite; do
  vault read -format=json "database/creds/chatbot-$role" > "$TMP_WORK/$role.json"
done
kv_read chatbot/research > "$TMP_WORK/research.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/research.json" > "$TMP_WORK/basic.headers"
printf 'grant_type=client_credentials&scope=openid%%20profile%%20email' > "$TMP_WORK/form"
http POST "$TENANT/oauth2/token" "$TMP_WORK/actor.json" "$TMP_WORK/basic.headers" --data-binary "@$TMP_WORK/form"
kv_read chatbot/oidc > "$TMP_WORK/oidc.json"
jq -jr '"Authorization: Basic "+((.client_id+":"+.client_secret)|@base64)+"\nContent-Type: application/x-www-form-urlencoded\n"' "$TMP_WORK/oidc.json" > "$TMP_WORK/oidc.headers"
http POST "$TENANT/oauth2/token" "$TMP_WORK/oidc-actor.json" "$TMP_WORK/oidc.headers" --data-binary "@$TMP_WORK/form"
vault token create -format=json -policy=chatbot-bootstrap -no-default-policy -ttl=5m -explicit-max-ttl=5m > "$TMP_WORK/bootstrap.json"
export CHATBOT_TEST_DIR="$TMP_WORK" CHATBOT_DIR
/tmp/vault-chatbot-venv/bin/python <<'PY'
import json, os, pathlib, ssl, datetime
import httpx, pymysql
d=pathlib.Path(os.environ['CHATBOT_TEST_DIR']); results=[]
def record(name, ok):
    results.append({'test':name,'passed':bool(ok)})
    print(name+': '+('PASS' if ok else 'FAIL'))
for role in ('readonly','readwrite'):
    c=json.loads((d/(role+'.json')).read_text())['data']
    with pymysql.connect(host='127.0.0.1',port=13306,user=c['username'],password=c['password'],database='scripting',autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM energy_plans'); record(role+'_select',cur.fetchone()[0]>=3)
            cur.execute('SELECT ID,server_name FROM test_encryption ORDER BY ID DESC LIMIT 20')
            record(role+'_inventory_select',len(cur.fetchall())>=1)
            try:
                cur.execute("INSERT INTO service_requests(subject_id,plan_id,note) VALUES('infrastructure-test',1,'rollback verification')")
                allowed=True
                conn.rollback()
            except pymysql.err.OperationalError as exc:
                if exc.args[0]!=1142: raise
                allowed=False
            record(role+'_insert_'+('allowed' if role=='readwrite' else 'denied'), allowed==(role=='readwrite'))
token=json.loads((d/'actor.json').read_text())['access_token']
with httpx.Client(verify=ssl.create_default_context(cafile=os.environ['VAULT_CACERT']),timeout=30) as client:
    h={'X-Vault-Token':token,'X-Vault-Namespace':'verify'}
    r=client.get(os.environ['VAULT_ADDR']+'/v1/secrets/data/tavily',headers=h)
    record('registered_research_agent_tavily_read',r.status_code==200)
    key=r.json()['data']['data']['TAVILY_API_KEY']
    for path in ('database/creds/chatbot-readwrite','secrets/data/verify-admin','secrets/data/chatbot/oidc','secrets/data/xai'):
        r=client.get(os.environ['VAULT_ADDR']+'/v1/'+path,headers=h)
        record('research_denied_'+path.replace('/','_'),r.status_code==403)
    actor=json.loads((d/'oidc-actor.json').read_text())['access_token']
    r=client.get(os.environ['VAULT_ADDR']+'/v1/database/creds/chatbot-readwrite',headers={**h,'X-Vault-Token':actor})
    record('database_agent_without_human_obo_denied',r.status_code==403)
    bootstrap=json.loads((d/'bootstrap.json').read_text())['auth']['client_token']
    bh={**h,'X-Vault-Token':bootstrap}
    for path in ('database/creds/chatbot-readwrite','secrets/data/tavily','secrets/data/verify-admin','secrets/data/chatbot/users/writer'):
        r=client.get(os.environ['VAULT_ADDR']+'/v1/'+path,headers=bh)
        record('bootstrap_denied_'+path.replace('/','_'),r.status_code==403)
    r=client.post(os.environ['VAULT_ADDR']+'/v1/auth/token/revoke-self',headers=bh)
    record('bootstrap_revoke_self',r.status_code==204)
with httpx.Client(timeout=40) as client:
    r=client.post('https://api.tavily.com/search',headers={'Authorization':'Bearer '+key},json={'query':'autoconsumo solar España','max_results':1,'search_depth':'basic'})
    record('tavily_live_search',r.status_code==200 and bool(r.json().get('results')))
report={'checked_at':datetime.datetime.now(datetime.UTC).isoformat(),'scope':'MySQL privileges and autonomous research; OBO tested separately','tests':results,'all_passed':all(r['passed'] for r in results)}
(pathlib.Path(os.environ['CHATBOT_DIR'])/'docs/infrastructure-tests.json').write_text(json.dumps(report,indent=2)+'\n')
PY
for role in readonly readwrite; do
  lease=$(jq -er .lease_id "$TMP_WORK/$role.json")
  vault lease revoke "$lease" >/dev/null
done
jq -e '.all_passed' "$CHATBOT_DIR/docs/infrastructure-tests.json" >/dev/null
