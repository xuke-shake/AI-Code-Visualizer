from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.schemas.auth import LoginIn, RegisterIn
from app.schemas.user import UserOut
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    result = AuthService(db).register(payload)
    AuditService(db).record(result.user.id, "auth.register", "user", result.user.id, request=request)
    db.commit()
    return success(result.model_dump(), trace_id=request_trace_id(request))


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    result = AuthService(db).login(payload)
    AuditService(db).record(result.user.id, "auth.login", "user", result.user.id, request=request)
    db.commit()
    return success(result.model_dump(), trace_id=request_trace_id(request))


@router.post("/token", include_in_schema=False)
def token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    payload = LoginIn(email=form_data.username, password=form_data.password)
    result = AuthService(db).login(payload)
    return {
        "access_token": result.access_token,
        "token_type": result.token_type,
    }


@router.get("/me")
def me(request: Request, current_user: User = Depends(get_current_user)):
    return success(UserOut.model_validate(current_user).model_dump(), trace_id=request_trace_id(request))