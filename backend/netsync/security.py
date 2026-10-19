from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from netsync.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except VerifyMismatchError:
        return False


def create_token(user_id: int) -> str:
    s = get_settings()
    exp = datetime.now(UTC) + timedelta(minutes=s.token_ttl_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, s.secret_key, algorithm="HS256")


def decode_token(token: str) -> int | None:
    try:
        return int(jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
