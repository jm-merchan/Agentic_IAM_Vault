path "database/creds/chatbot-readonly" { capabilities = ["read"] }
path "database/creds/chatbot-readwrite" { capabilities = ["read"] }
path "transit/encrypt/lumen-applications" { capabilities = ["update"] }
path "transform/encode/lumen-dni" { capabilities = ["update"] }
path "transform/encode/lumen-iban" { capabilities = ["update"] }
