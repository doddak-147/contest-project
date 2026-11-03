from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from fastapi import HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import delete, func, select

from .domain import utc_now
from .models import AuthAttempt, LoginSession, User

PASSWORDS = PasswordHash.recommended()
DUMMY_HASH = PASSWORDS.hash("contestly-timing-placeholder-password")
SESSION_COOKIE = "contestly_session"
CSRF_COOKIE = "contestly_csrf"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(request: Request):
    origin = request.headers.get("origin")
    expected = request.app.state.settings.public_origin or str(request.base_url).rstrip("/")
    if origin and origin.rstrip("/") != expected:
        raise HTTPException(403, "다른 사이트에서 보낸 요청은 허용되지 않습니다.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "요청 출처를 확인할 수 없습니다.")


def get_user(request, db, required=True):
    token = request.cookies.get(SESSION_COOKIE, "")
    session = db.get(LoginSession, digest(token)) if token else None
    user = db.get(User, session.user_id) if session and session.expires_at > utc_now() else None
    if required and not user:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def require_csrf(request, db):
    check_origin(request)
    user = get_user(request, db)
    token = request.cookies.get(SESSION_COOKIE, "")
    session = db.get(LoginSession, digest(token))
    csrf = request.headers.get("x-csrf-token", "")
    if not csrf or not secrets.compare_digest(digest(csrf), session.csrf_hash):
        raise HTTPException(403, "요청 확인에 실패했습니다. 새로고침 후 다시 시도하세요.")
    return user


def require_admin(request, db, write=False):
    user = require_csrf(request, db) if write else get_user(request, db)
    if user.role != "admin":
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return user


def issue_session(request: Request, response: Response, db, user):
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(old)))
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= utc_now()))
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    settings = request.app.state.settings
    expires = (datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)).isoformat(timespec="seconds")
    db.add(LoginSession(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf), expires_at=expires))
    db.commit()
    options = {"secure": settings.secure_cookies, "samesite": "lax", "max_age": settings.session_hours * 3600, "path": "/"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **options)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **options)
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_payload(user), "csrf_token": csrf}


def user_payload(user):
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}


def throttle_auth(request, db):
    # Shared database counter, including across workers; no password or raw IP in logs.
    bucket = digest(request.client.host if request.client else "unknown")
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    db.execute(delete(AuthAttempt).where(AuthAttempt.created_at < cutoff))
    count = db.scalar(select(func.count()).select_from(AuthAttempt).where(AuthAttempt.bucket == bucket))
    if count >= 20:
        db.commit()
        raise HTTPException(429, "로그인 시도가 많습니다. 잠시 후 다시 시도하세요.", headers={"Retry-After": "600"})
    db.add(AuthAttempt(bucket=bucket, created_at=utc_now()))
    db.commit()
