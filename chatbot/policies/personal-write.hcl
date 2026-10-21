# Ceiling only; no autonomous policy is attached to the agent entity.
path "secrets/data/lumen-personal/*" { capabilities = ["create", "read", "update"] }
path "secrets/metadata/lumen-personal/*" { capabilities = ["list"] }
