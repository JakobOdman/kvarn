"""
auth.py - who is logged in: the Supabase access token in "Authorization: Bearer <token>".

Supabase signs the tokens with its private key (ES256). They are checked with its public keys (JWKS),
so no secret is needed on the server. Accounts are made in Supabase (Authentication -> Users).
"""
import os

import jwt

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://qnzdejhsxdtqnfelmrbq.supabase.co")
ISSUER = f"{SUPABASE_URL}/auth/v1"

_keys = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", cache_keys=True)


def user_from_token(token: str) -> dict | None:
    """{"id", "email", "name"} for a valid, unexpired token from our Supabase project, otherwise None."""
    try:
        key = _keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key, algorithms=["ES256"], audience="authenticated", issuer=ISSUER)
    except jwt.PyJWTError:
        return None
    name = (claims.get("user_metadata") or {}).get("name") or claims.get("email", "")
    return {"id": claims["sub"], "email": claims.get("email", ""), "name": name}
