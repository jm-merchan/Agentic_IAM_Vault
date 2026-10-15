# Values stay in memory / private temporary files. Only booleans and lengths escape.
def attrs: .attributes | map({key, value:(.value | if has("stringValue") then .stringValue elif has("boolValue") then .boolValue else .intValue end)}) | from_entries;
[$spans[0][] | select(.name=="vault.read" or .name=="vault.write") | attrs | select(.["vault.capture.raw"]==true) |
 . as $a |
 (.["vault.http.request"]|fromjson) as $req |
 (.["vault.http.response"]|fromjson) as $res |
 (.["vault.auth.jwt"]|fromjson) as $jwt |
 [$audit[0][]|select(.request.headers.traceparent[0]==$req.headers.traceparent and ._lumen_audit_mode=="raw")] as $events |
 {
   path:$a["vault.path"],http_status:($a["http.response.status_code"]|tonumber),jwt_bytes:($jwt|utf8bytelength),
   jwt_matches_sent_header:($jwt==$req.headers["X-Vault-Token"]),
   jwt_matches_both_audit_events:(($events|length)==2 and all($events[];.auth.client_token==$jwt)),
   request_body_matches_audit:(if $req.method=="POST" then any($events[];.type=="request" and .request.data==$req.body) else true end),
   vault_response_data_matches_audit:(if $res.status_code==200 then any($events[];.type=="response" and .response.data==$res.body.data) else $res.status_code==403 end),
   content_complete:([$a|to_entries[]|select(.key|test("^vault\\..*\\.truncated$"))|.value]|length==4 and all(.[];.==false))
 } | . + {passed:(.jwt_matches_sent_header and .jwt_matches_both_audit_events and .request_body_matches_audit and .vault_response_data_matches_audit and .content_complete)}]
