import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from anyio import to_thread
from cryptography.fernet import Fernet
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"


def evaluation_cipher() -> Fernet:
    """Build the app-bound cipher for request credentials stored in the DB."""
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_evaluation_headers(headers: dict[str, str]) -> str:
    return evaluation_cipher().encrypt(json.dumps(headers).encode()).decode()


def decrypt_evaluation_headers(value: str) -> dict[str, str]:
    if not value:
        return {}
    payload = json.loads(evaluation_cipher().decrypt(value.encode()))
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in payload.items()
    ):
        raise ValueError("Stored evaluation headers are invalid")
    return payload


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(UTC) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


async def verify_password_async(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return await to_thread.run_sync(verify_password, plain_password, hashed_password)


async def get_password_hash_async(password: str) -> str:
    return await to_thread.run_sync(get_password_hash, password)
