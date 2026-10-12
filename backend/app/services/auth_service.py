from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.exceptions import ConflictException, ForbiddenException, UnauthorizedException
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.quota import Quota
from app.models.user import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def register(self, payload: RegisterIn) -> TokenOut:
        email = self._normalize_email(payload.email)
        exists = self.db.scalar(select(User).where(func.lower(User.email) == email))
        if exists:
            raise ConflictException("邮箱已注册")
        user = User(
            email=email,
            password_hash=get_password_hash(payload.password),
            nickname=payload.nickname,
            role="user",
            status="normal",
        )
        try:
            self.db.add(user)
            self.db.flush()
            self.db.add(Quota(user_id=user.id))
            # The API handler owns the short request transaction so audit
            # records and user/quota rows commit or roll back together.
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictException("邮箱已注册") from exc
        self.db.refresh(user)
        token = create_access_token(user.id, {"role": user.role})
        return TokenOut(access_token=token, user=user)

    def login(self, payload: LoginIn) -> TokenOut:
        email = self._normalize_email(payload.email)
        user = self.db.scalar(select(User).where(func.lower(User.email) == email))
        if user and user.password_hash.startswith(("$2a$", "$2b$", "$2y$")) and len(payload.password.encode("utf-8")) > 72:
            raise UnauthorizedException("历史 bcrypt 长密码需要受控重置，不能继续使用")
        if not user or not verify_password(payload.password, user.password_hash):
            raise UnauthorizedException("邮箱或密码错误")
        if user.status != "normal":
            raise ForbiddenException("账号已被禁用")
        user.last_login_at = datetime.now(timezone.utc)
        self.db.flush()
        token = create_access_token(user.id, {"role": user.role})
        return TokenOut(access_token=token, user=user)

    @staticmethod
    def _normalize_email(value: str) -> str:
        return str(value).strip().casefold()
