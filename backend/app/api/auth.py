"""Signup / login / session. Passwords are bcrypt-hashed; Canvas tokens are Fernet-encrypted and
never returned to the client."""

from __future__ import annotations

import logging
import re
import secrets

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    encrypt_secret,
    hash_password,
    is_password_hash,
    verify_legacy_plaintext,
    verify_password,
)
from app.database.academic_repository import get_academic_repo
from app.models.schemas import CanvasTokenUpdate, LoginRequest, SignupRequest, TokenResponse

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


def _derive_user_id(email: str) -> str:
    """Keep the prototype's student-number ids (s1234567@... -> 1234567) when possible."""
    m = re.match(r"^[a-z](\d{5,9})@", email.lower())
    return m.group(1) if m else str(secrets.randbelow(10**9 - 10**8) + 10**8)


async def _payload(request: Request, model):
    """Accept JSON bodies (current frontend) and query params (original prototype)."""
    data = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data = await request.json() or {}
        except ValueError:
            data = {}
    if not data:
        data = dict(request.query_params)
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors(include_url=False, include_context=False))


@router.post("/signup", status_code=201)
async def signup(request: Request):
    body: SignupRequest = await _payload(request, SignupRequest)
    repo = get_academic_repo()
    email = body.email.lower()
    if repo.get_user_by_email(email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User with this email already exists")
    user_id = _derive_user_id(email)
    if repo.get_user(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An account already exists for this student number")
    repo.create_user({
        "user_id": user_id,
        "full_name": body.name.strip(),
        "email": email,
        "api_token": encrypt_secret(body.api_token.strip()) if body.api_token else None,
        "password": hash_password(body.password),
    })
    return {"message": "User created successfully", "data": {"user_id": user_id, "email": email}}


@router.post("/login", response_model=TokenResponse)
async def login(request: Request):
    body: LoginRequest = await _payload(request, LoginRequest)
    repo = get_academic_repo()
    user = repo.get_user_by_email(body.email.lower())
    stored = (user or {}).get("password")
    ok = verify_password(body.password, stored)
    if not ok and verify_legacy_plaintext(body.password, stored):
        ok = True
        repo.update_user(str(user["user_id"]), {"password": hash_password(body.password)})
        log.info("Migrated a legacy plaintext password to bcrypt")
    if not ok:
        # same message for unknown user and wrong password (no account enumeration)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect")
    user_id = str(user["user_id"])
    return TokenResponse(
        access_token=create_access_token(user_id), user_id=user_id, name=user.get("full_name"),
        expires_in=get_settings().jwt_ttl_minutes * 60,
    )


@router.get("/me")
def me(user_id: str = CurrentUser):
    user = get_academic_repo().get_user(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return {
        "user_id": str(user["user_id"]),
        "name": user.get("full_name"),
        "email": user.get("email"),
        "has_canvas_token": bool(user.get("api_token")),
        "password_migrated": is_password_hash(user.get("password")),
    }


@router.put("/me/canvas-token")
def update_canvas_token(body: CanvasTokenUpdate, user_id: str = CurrentUser):
    get_academic_repo().update_user(user_id, {"api_token": encrypt_secret(body.api_token.strip())})
    return {"message": "Canvas token updated"}
