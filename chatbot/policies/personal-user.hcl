# The OBO subject is the human entity. Every user receives the same template.
path "secrets/data/lumen-personal/{{identity.entity.id}}/*" {
  capabilities = ["create", "read", "update"]
}
path "secrets/metadata/lumen-personal/{{identity.entity.id}}/*" {
  capabilities = ["list"]
}
path "secrets/metadata/lumen-personal/{{identity.entity.id}}" {
  capabilities = ["list"]
}
