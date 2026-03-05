# API Key Lifecycle
# 1. Operator calls POST /keys with X-Admin-Token header to issue a new key.
# 2. The plaintext key is returned once and never stored.
# 3. The SHA256 hash of the key is stored in Postgres.
# 4. On each request, the Bearer token is hashed and compared against stored hashes.
# 5. Keys can be deactivated by setting is_active=False in the database.

import hashlib
import os
import secrets

from fastapi import Depends, Header, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .db_models import APIKeyORM


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_key() -> str:
    return secrets.token_urlsafe(32)


async def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer()),
    db: Session = Depends(get_db),
) -> APIKeyORM:
    key_hash = hash_key(credentials.credentials)
    record = (
        db.query(APIKeyORM)
        .filter(APIKeyORM.key_hash == key_hash, APIKeyORM.is_active == True)  # noqa: E712
        .first()
    )
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return record


def require_admin_token(x_admin_token: str = Header(...)) -> None:
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=500, detail="Admin token not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token")
