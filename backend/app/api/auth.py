from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.models import LoginLog, User
from app.schemas import LoginRequest, RefreshRequest, TokenResponse, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["认证"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_token(user.id),
        refresh_token=create_token(user.id, "refresh"),
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> TokenResponse:
    duplicate = db.scalar(
        select(User).where(or_(User.username == payload.username, User.email == payload.email))
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在")
    user = User(
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role="customer",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    success = bool(user and user.is_active and verify_password(payload.password, user.password_hash))
    db.add(
        LoginLog(
            user_id=user.id if user else None,
            username=payload.username,
            success=success,
            ip_address=request.client.host if request.client else None,
        )
    )
    db.commit()
    if not success or not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        token_data = decode_token(payload.refresh_token, "refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="刷新令牌无效") from exc
    user = db.get(User, token_data.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不可用")
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
