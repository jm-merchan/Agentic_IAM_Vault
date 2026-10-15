# Runtime inference only. The application cannot administer xAI or read its management key.
path "xai/creds/lumen" { capabilities = ["read"] }
# Reauthorize cached inference keys through a real Vault read on every run.
path "secrets/data/chatbot/xai-access" { capabilities = ["read"] }
