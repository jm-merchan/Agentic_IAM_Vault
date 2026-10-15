# A Transform request can appear on two nodes with the same request ID.
# The internal forwarding copy has no auth; keep the authenticated raw event.
# Original copies remain in Loki. Do not relax JWT/body/response comparisons.
[.data.result[] | .stream.audit_mode as $mode | .values[][1] | fromjson |
 . + {_lumen_audit_mode:($mode // "hmac")}]
| group_by([.request.id,.type])
| map(sort_by([
    (if ._lumen_audit_mode=="raw" then 1 else 0 end),
    (if ((.auth.client_token // "")|length)>0 then 1 else 0 end)
  ]) | last)
| [.[] | select(.type=="response" and .error=="please forward to the active node") | .request.id] as $forwarded
| map(select(.request.id as $id | $forwarded | index($id) | not))
