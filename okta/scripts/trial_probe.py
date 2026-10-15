#!/usr/bin/env python3
"""Check trial Client Credentials entitlement without logging credentials/tokens."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives.asymmetric import ec
import jwt

from agentic_demo import validate
from terraform_okta import vault_read


def main():
    config = vault_read("okta-trial-probe")
    issuer = "https://trial-2604851.okta.com/oauth2/default"
    if config["issuer"] != issuer or config["jwks_uri"] != issuer + "/v1/keys":
        raise RuntimeError("Unexpected trial destination")
    endpoint = issuer + "/v1/token"
    key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    credentials = config["client_id"] + ":" + config["client_secret"]
    nonce = None
    attempts = []
    for _ in range(3):
        proof_claims = {
            "jti": secrets.token_urlsafe(32), "htm": "POST", "htu": endpoint,
            "iat": int(time.time()),
        }
        if nonce:
            proof_claims["nonce"] = nonce
        proof = jwt.encode(proof_claims, key, algorithm="ES256",
                           headers={"typ": "dpop+jwt", "jwk": public_jwk})
        request = urllib.request.Request(endpoint, data=urllib.parse.urlencode({
            "grant_type": "client_credentials", "scope": config["scope"],
        }).encode(), headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
            "DPoP": proof,
        })
        try:
            response = urllib.request.urlopen(request, timeout=25)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.status
            body = json.loads(response.read())
            nonce = response.headers.get("DPoP-Nonce")
        attempts.append({"http_status": status, "error": body.get("error")})
        if body.get("error") == "use_dpop_nonce" and nonce:
            continue
        break
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "issuer": issuer, "client_id": config["client_id"], "scope": config["scope"],
        "grant_type": "client_credentials", "dpop_enabled": True,
        "attempts": attempts, "http_status": status,
    }
    if status == 200:
        claims = validate(body["access_token"], config)
        if claims["sub"] != config["client_id"] or config["scope"] not in claims.get("scp", []):
            raise RuntimeError("Unexpected token subject or scope")
        result.update(signature_verified=True, token_type=body.get("token_type"),
                      claims={k: claims.get(k) for k in ("iss", "aud", "sub", "scp", "exp", "cnf")})
    else:
        result.update(error=body.get("error"), error_description=body.get("error_description"))
    # Only non-secret evidence is persisted. Tokens and the DPoP key remain in memory.
    target = Path(__file__).resolve().parents[1] / "docs" / "trial-probe-result.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
