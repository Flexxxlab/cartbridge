"""Minimal server-rendered site: sign up, verify email, log in, manage API keys."""
import re
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .emailer import send_email
from .models import ApiKey, EmailToken, User, utcnow
from .security import hash_password, new_api_key, new_csrf, new_token, sha256_hex, verify_password

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# A real hash so failed logins for unknown users take the same time as for real ones.
_DUMMY_HASH = hash_password("timing-equalizer")


# ---------- helpers ----------
def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = new_csrf()
    return request.session["csrf"]


def check_csrf(request: Request, token: str) -> None:
    if not token or token != request.session.get("csrf"):
        raise HTTPException(400, "Invalid form token. Reload the page and try again.")


def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    ctx.update(app_name=get_settings().app_name, csrf=csrf_token(request), user=ctx.get("user"))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def current_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    return user if user and user.is_active else None


def send_verification(db: Session, user: User, background: BackgroundTasks) -> None:
    s = get_settings()
    raw, h = new_token()
    db.add(EmailToken(user_id=user.id, token_hash=h, purpose="verify",
                      expires_at=utcnow() + timedelta(hours=s.email_token_ttl_hours)))
    db.commit()
    link = f"{s.base_url.rstrip('/')}/verify?token={raw}"
    body = (f"Hi {user.username},\n\nConfirm your email to start creating API keys:\n{link}\n\n"
            f"This link expires in {s.email_token_ttl_hours} hours. If you didn't sign up, ignore this email.")
    background.add_task(send_email, user.email, f"Verify your {s.app_name} account", body)


# ---------- pages ----------
@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse("/dashboard" if current_user(request, db) else "/login", status_code=303)


@router.get("/signup")
def signup_form(request: Request):
    return render(request, "signup.html")


@router.post("/signup")
def signup(
    request: Request,
    background: BackgroundTasks,
    username: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    username, email = username.strip(), email.strip().lower()
    errors = []
    if not USERNAME_RE.match(username):
        errors.append("Username must be 3–32 characters: letters, numbers, underscore.")
    if not EMAIL_RE.match(email) or len(email) > 254:
        errors.append("Enter a valid email address.")
    if len(password) < 8 or len(password) > 128:
        errors.append("Password must be 8–128 characters.")
    if password != password2:
        errors.append("Passwords don't match.")
    if not errors:
        if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
            errors.append("That username is taken.")
        if db.scalar(select(User).where(User.email == email)):
            errors.append("An account with that email already exists.")
    if errors:
        return render(request, "signup.html", 400, errors=errors, username=username, email=email)

    user = User(username=username, email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    send_verification(db, user, background)
    request.session.clear()
    request.session["uid"] = user.id
    return render(request, "message.html", title="Check your email",
                  message=f"We sent a verification link to {email}. Click it to activate API keys.", user=user)


@router.get("/verify")
def verify(request: Request, token: str = "", db: Session = Depends(get_db)):
    t = db.scalar(select(EmailToken).where(EmailToken.token_hash == sha256_hex(token), EmailToken.purpose == "verify"))
    if not t or t.used_at or t.expires_at < utcnow():
        return render(request, "message.html", 400, title="Link invalid or expired",
                      message="Log in and use “Resend verification email” to get a new link.")
    user = db.get(User, t.user_id)
    t.used_at = utcnow()
    if user and not user.email_verified_at:
        user.email_verified_at = utcnow()
    db.commit()
    return render(request, "message.html", title="Email verified",
                  message="Your email is verified. You can now create API keys.",
                  link=("/dashboard", "Go to dashboard"))


@router.post("/verify/resend")
def resend(request: Request, background: BackgroundTasks, csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.is_verified:
        send_verification(db, user, background)
    return render(request, "message.html", title="Email sent",
                  message=f"A new verification link was sent to {user.email}.", user=user,
                  link=("/dashboard", "Back to dashboard"))


@router.get("/login")
def login_form(request: Request):
    return render(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        return render(request, "login.html", 400, errors=["Wrong username or password."], username=username)
    request.session.clear()  # rotate session on login
    request.session["uid"] = user.id
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), new_key: str | None = None):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())).all()
    return render(request, "dashboard.html", user=user, keys=keys, new_key=new_key,
                  base_url=get_settings().base_url.rstrip("/"))


@router.post("/keys")
def create_key(request: Request, name: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.is_verified:
        raise HTTPException(403, "Verify your email before creating API keys.")
    active = db.scalar(select(func.count()).select_from(ApiKey)
                       .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None)))
    if active >= get_settings().max_api_keys_per_user:
        raise HTTPException(400, "API key limit reached. Revoke an old key first.")
    raw, prefix, h = new_api_key()
    db.add(ApiKey(user_id=user.id, name=(name.strip() or "Default")[:60], prefix=prefix, key_hash=h))
    db.commit()
    # Render directly (not redirect) so the raw key never lands in a URL or log.
    return dashboard(request, db, new_key=raw)


@router.post("/keys/{key_id}/revoke")
def revoke_key(request: Request, key_id: int, csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    key = db.get(ApiKey, key_id)
    if key and key.user_id == user.id and not key.revoked_at:
        key.revoked_at = utcnow()
        db.commit()
    return RedirectResponse("/dashboard", status_code=303)
