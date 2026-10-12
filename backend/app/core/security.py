from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException

pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
settings = get_settings()


def verify_password(plain_password: str, password_hash: str) -> bool:
    if password_hash.startswith(("$2a$", "$2b$", "$2y$")) and len(plain_password.encode("utf-8")) > 72:
        return False
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except (JWTError, TypeError, ValueError) as exc:
        raise UnauthorizedException() from exc
    if not isinstance(payload, dict):
        raise UnauthorizedException()
    raw_subject = payload.get("sub")
    if isinstance(raw_subject, bool):
        raise UnauthorizedException()
    if isinstance(raw_subject, bool):
        raise UnauthorizedException()
    if isinstance(raw_subject, int):
        subject_number = raw_subject
    elif isinstance(raw_subject, str) and raw_subject.isdigit():
        try:
            subject_number = int(raw_subject)
        except (ValueError, OverflowError):
            raise UnauthorizedException()
    else:
        raise UnauthorizedException()
    if subject_number <= 0:
        raise UnauthorizedException()
    subject = str(subject_number)
    payload["sub"] = subject
    return payload
