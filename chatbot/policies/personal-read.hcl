# Ceiling only; the human ACL restricts this prefix to the subject's entity ID.
path "secrets/data/lumen-personal/*" { capabilities = ["read"] }
path "secrets/metadata/lumen-personal/*" { capabilities = ["list"] }
