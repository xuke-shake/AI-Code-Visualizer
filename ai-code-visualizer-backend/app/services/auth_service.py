from datetime import datetime, timezone
from sqlalchemy import select
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
        exists = self.db.scalar(select(User).where(User.email == payload.email))
        if exists:
            raise ConflictException("邮箱已注册")
        user = User(
            email=str(payload.email).lower(),
            password_hash=get_password_hash(payload.password),
            nickname=payload.nickname,
            role="user",
            status="normal",
        )
        self.db.add(user)
        self.db.flush()
        self.db.add(Quota(user_id=user.id))
        self.db.commit()
        self.db.refresh(user)
        token = create_access_token(user.id, {"role": user.role})
        return TokenOut(access_token=token, user=user)

    def login(self, payload: LoginIn) -> TokenOut:
        user = self.db.scalar(select(User).where(User.email == str(payload.email).lower()))
        if not user or not verify_password(payload.password, user.password_hash):
            raise UnauthorizedException("邮箱或密码错误")
        if user.status != "normal":
            raise ForbiddenException("账号已被禁用")
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        token = create_access_token(user.id, {"role": user.role})
        return TokenOut(access_token=token, user=user)
