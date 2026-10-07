"""API-key authentication.

Keys are 256-bit random tokens, so a fast hash (SHA-256) is enough: unlike passwords they cannot
be guessed or brute-forced, and a deterministic hash lets the key be looked up by an index.
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiClient

KEY_PREFIX = "gm_"


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_client(session: Session, name: str) -> tuple[ApiClient, str]:
    """Create a client and return it with its API key (the only time the key is available)."""
    key = generate_key()
    client = ApiClient(name=name[:100], key_hash=hash_key(key), key_prefix=key[:10])
    session.add(client)
    session.commit()
    return client, key


def authenticate(session: Session, key: str) -> ApiClient | None:
    return session.scalar(select(ApiClient).where(ApiClient.key_hash == hash_key(key)))
