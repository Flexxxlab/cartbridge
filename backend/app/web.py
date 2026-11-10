"""Minimal server-rendered site: sign up, verify email, log in, manage API keys."""
import re
from datetime import timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .auth_email import deliver_reset, deliver_verification, issue_token
from .db import SessionLocal, get_db
from .crypto import encrypt
from .models import ApiKey, EmailToken, PlatformAccess, User, UserLimits, WalmartCredential, utcnow
from .plans import PLANS, get_plan
from .providers import walmart_source
from .ratelimit import (MAX_COUNT, WINDOW_CHOICES, ceiling_for, chosen_for, default_chosen, describe_window,
                        limits_for, monthly_limit_for, parse_limits, plan_name_for, usage_for, describe_plan)
from .throttle import key_for_email, retry_after, throttled, WHAT
from . import seo, ux
from .stores import WalmartAffiliateProvider
from .stores.base import StoreError
from .security import hash_password, new_api_key, new_csrf, sha256_hex, verify_password

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


def render(request: Request, name: str, status_code: int = 200, indexable: bool = False,
           description: str | None = None, page_title: str | None = None, **ctx) -> HTMLResponse:
    """Render a template with the shared layout. Only pages passed indexable=True get canonical/OG/JSON-LD;
    everything else (dashboard, forms, admin, messages) is noindex."""
    cfg = get_settings()
    site = cfg.base_url.rstrip("/")
    ctx.update(app_name=cfg.app_name, csrf=csrf_token(request), user=ctx.get("user"),
               support_email=cfg.support_email, company_name=cfg.company_name, company_url=cfg.company_url,
               source_url=cfg.source_url, year=utcnow().year, contact_url=ux.contact_url(),
               contact_to_buy=ux.CONTACT_TO_BUY, verify_notice=ux.verify_notice(),
               forgot_password=ux.forgot_password(), email_enabled=cfg.email_enabled, site_url=site, indexable=indexable,
               description=description, page_title=page_title, default_description=seo.DEFAULT_DESCRIPTION,
               canonical=site + request.url.path.rstrip("/") if indexable and request.url.path != "/" else site + "/",
               jsonld=seo.jsonld() if indexable else "",
               breadcrumb_ld=seo.breadcrumb_jsonld(request.url.path) if indexable else "")
    if indexable and name in ("faq.html", "home.html"):
        items = seo.faq_items(seo.describe_free(), cfg.email_enabled, ux.contact_url(), cfg.support_email)
        if name == "home.html":
            keep = ("faq-what", "faq-server", "faq-account", "faq-key", "faq-limits", "faq-stores")
            items = [i for i in items if i["id"] in keep]
        ctx.update(faq_items=items, faq_ld=seo.faq_jsonld(items))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def is_admin(user: User | None) -> bool:
    admins = get_settings().admins
    return bool(user and user.is_verified and (user.username.lower() in admins or user.email.lower() in admins))


def current_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    if not user or not user.is_active:
        return None
    if request.session.get("sv", 0) != user.session_version:  # password was changed or reset since this login
        request.session.clear()
        return None
    return user


def start_session(request: Request, user: User) -> None:
    request.session.clear()  # rotate session on login
    request.session["uid"] = user.id
    request.session["sv"] = user.session_version


def send_verification(db: Session, user: User, background: BackgroundTasks) -> None:
    raw, h = issue_token(db, user, "verify", timedelta(hours=get_settings().email_token_ttl_hours))
    background.add_task(deliver_verification, user, raw, h)


def _sensitive(resp: HTMLResponse) -> HTMLResponse:
    """Pages reached from an emailed link: don't cache, don't leak the URL (token) via Referer."""
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _consume_token(db: Session, token: str, purpose: str) -> EmailToken | None:
    """Atomically marks a valid, unused, unexpired token used and returns it; None if it can't be used."""
    if not token:
        return None
    t = db.scalar(select(EmailToken).where(EmailToken.token_hash == sha256_hex(token), EmailToken.purpose == purpose))
    if not t or t.used_at or t.expires_at < utcnow():
        return None
    res = db.execute(update(EmailToken).where(EmailToken.id == t.id, EmailToken.used_at.is_(None))
                     .values(used_at=utcnow()))
    db.commit()
    return t if res.rowcount == 1 else None


def _live_token(db: Session, token: str, purpose: str) -> bool:
    t = db.scalar(select(EmailToken).where(EmailToken.token_hash == sha256_hex(token or ""), EmailToken.purpose == purpose))
    return bool(t and not t.used_at and t.expires_at >= utcnow())


# ---------- pages ----------
@router.get("/signup")
def signup_form(request: Request):
    return render(request, "signup.html", indexable=True, page_title="Sign up free · CartBridge",
                  description="Create a free CartBridge account: bring your own Walmart key and add Walmart "
                              "add-to-cart to your app with one API call.")


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
    if blocked := throttled(request, db, "signup", render):
        return blocked
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
    start_session(request, user)
    return render(request, "message.html", title="Check your email", user=user,
                  message=(f"We created your account for {email} and sent a verification link "
                           f"(it expires in {get_settings().email_token_ttl_hours} hours; check spam too)."
                           if get_settings().email_enabled else
                           f"We created your account for {email} and sent a verification link."),
                  notice=ux.verify_notice())


@router.get("/verify")
def verify_form(request: Request, token: str = "", db: Session = Depends(get_db)):
    """Shows a confirm button; only the POST uses the token up, so mail scanners that open links can't burn it."""
    if not _live_token(db, token, "verify"):
        return _sensitive(render(request, "message.html", 400, title="Link invalid or expired",
                                 message="Log in and use “Resend verification email” to get a new link."))
    return _sensitive(render(request, "verify.html", token=token))


@router.post("/verify")
def verify(request: Request, token: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    t = _consume_token(db, token, "verify")
    if not t:
        return _sensitive(render(request, "message.html", 400, title="Link invalid or expired",
                                 message="Log in and use “Resend verification email” to get a new link."))
    user = db.get(User, t.user_id)
    if user and not user.email_verified_at:
        user.email_verified_at = utcnow()
        db.commit()
    return _sensitive(render(request, "message.html", title="Email verified",
                             message="Your email is verified. You can now create API keys.",
                             link=("/dashboard", "Go to dashboard")))


@router.post("/verify/resend")
def resend(request: Request, background: BackgroundTasks, csrf: str = Form(""), db: Session = Depends(get_db)):
    if blocked := throttled(request, db, "resend", render):
        return blocked
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if wait := retry_after(db, f"acct:{user.id}", "resend_acct"):
        resp = render(request, "message.html", 429, title="Too many attempts", user=user,
                      message=ux.throttle_message(WHAT["resend_acct"], wait).replace("from your network", "for your account"))
        resp.headers["Retry-After"] = str(wait)
        return resp
    if not user.is_verified:
        send_verification(db, user, background)
    return render(request, "message.html", title="Email sent",
                  message=f"A new verification link was sent to {user.email}.", user=user,
                  notice=ux.verify_notice(), link=("/dashboard", "Back to dashboard"))


# ---------- forgot / reset password ----------
FORGOT_SENT = "If an account exists for that email, we sent a link to reset the password. It expires in {m} minutes."


def _reset_task(email: str) -> None:
    """Runs after the response is sent, so the reply is the same whether or not the account exists."""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if not user or not user.is_active:
            return
        raw, h = issue_token(db, user, "reset", timedelta(minutes=get_settings().reset_token_ttl_minutes),
                               void_older=False)
        deliver_reset(user, raw, h)


@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "forgot.html")


@router.post("/forgot")
def forgot(request: Request, background: BackgroundTasks, email: str = Form(""), csrf: str = Form(""),
           db: Session = Depends(get_db)):
    if blocked := throttled(request, db, "forgot", render):  # per IP; the same for every address
        return blocked
    check_csrf(request, csrf)
    cfg = get_settings()
    if not cfg.email_enabled:  # fallback: no emails are sent, nothing is created
        return render(request, "forgot.html")
    email = email.strip().lower()[:254]
    # Per-address limit on a hash of the input, counted whether or not the account exists; over the limit we
    # just skip sending, so the response never changes.
    if not retry_after(db, key_for_email(email), "forgot_email") and EMAIL_RE.match(email):
        background.add_task(_reset_task, email)
    return render(request, "message.html", title="Check your email",
                  message=FORGOT_SENT.format(m=cfg.reset_token_ttl_minutes), link=("/login", "Back to log in"))


@router.get("/reset")
def reset_form(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not get_settings().email_enabled or not _live_token(db, token, "reset"):
        return _sensitive(render(request, "message.html", 400, title="Link invalid or expired",
                                 message="Request a new password reset link.", link=("/forgot", "Reset password")))
    return _sensitive(render(request, "reset.html", token=token))


@router.post("/reset")
def reset(request: Request, token: str = Form(""), password: str = Form(""), password2: str = Form(""),
          csrf: str = Form(""), db: Session = Depends(get_db)):
    if blocked := throttled(request, db, "reset", render):
        return blocked
    check_csrf(request, csrf)
    expired = _sensitive(render(request, "message.html", 400, title="Link invalid or expired",
                                message="Request a new password reset link.", link=("/forgot", "Reset password")))
    if not get_settings().email_enabled or not _live_token(db, token, "reset"):
        return expired
    errors = []
    if len(password) < 8 or len(password) > 128:
        errors.append("Password must be 8–128 characters.")
    if password != password2:
        errors.append("Passwords don't match.")
    if errors:  # token not used up: the user can try again
        return _sensitive(render(request, "reset.html", 400, token=token, errors=errors))
    t = _consume_token(db, token, "reset")
    user = db.get(User, t.user_id) if t else None
    if not user or not user.is_active:
        return expired
    user.password_hash = hash_password(password)
    user.session_version += 1  # logs out every browser session, including an attacker's
    if not user.email_verified_at:  # they just proved they control the mailbox
        user.email_verified_at = utcnow()
    db.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.used_at.is_(None))
               .values(used_at=utcnow()))  # voids other reset links and pending verification links
    revoked = db.execute(update(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
                         .values(revoked_at=utcnow())).rowcount
    db.commit()
    request.session.clear()
    note = (f" {revoked} API key{'s were' if revoked != 1 else ' was'} revoked as a precaution: create a new one "
            "on the dashboard and update your apps." if revoked else "")
    return render(request, "message.html", title="Password updated",
                  message="Your password was changed and you were logged out everywhere. Log in with the new one." + note,
                  link=("/login", "Log in"))


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
    if blocked := throttled(request, db, "login", render):
        return blocked
    check_csrf(request, csrf)
    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        return render(request, "login.html", 400, errors=["Wrong username or password."], username=username)
    start_session(request, user)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), new_key: str | None = None,
              walmart_error: str | None = None, walmart_saved: bool = False,
              limits_message: str | None = None, limits_error: str | None = None):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())).all()
    cred = db.scalar(select(WalmartCredential).where(WalmartCredential.user_id == user.id))
    return render(request, "dashboard.html", user=user, keys=keys, new_key=new_key,
                  base_url=get_settings().base_url.rstrip("/"),
                  walmart_source=walmart_source(db, user), walmart_cred=cred,
                  usage=usage_for(db, user), plan_name=plan_name_for(db, user),
                  plan_text=describe_plan(get_plan(user.plan)), monthly_cap=monthly_limit_for(db, user), is_admin=is_admin(user), **_limit_form(db, user),
                  limits_message=limits_message, limits_error=limits_error,
                  walmart_error=walmart_error, walmart_saved=walmart_saved)


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


def _parse_rsa_key(pem: str) -> str:
    """Returns the normalized PEM, or raises ValueError with a user-facing message."""
    pem = pem.strip().replace("\r\n", "\n")
    if "BEGIN" not in pem:
        raise ValueError("That doesn't look like a PEM private key (it should start with -----BEGIN).")
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except (ValueError, TypeError):
        raise ValueError("Could not read the private key. Use an unencrypted RSA key in PEM format.") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("The private key must be an RSA key.")
    return pem


@router.post("/walmart")
async def save_walmart(
    request: Request,
    consumer_id: str = Form(""),
    key_version: str = Form("1"),
    publisher_id: str = Form(""),
    private_key: str = Form(""),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.is_verified:
        raise HTTPException(403, "Verify your email first.")
    consumer_id, key_version, publisher_id = consumer_id.strip(), key_version.strip() or "1", publisher_id.strip()
    if not consumer_id or len(consumer_id) > 100 or not key_version.isdigit() or len(publisher_id) > 50:
        return dashboard(request, db, walmart_error="Enter your consumer ID and a numeric key version.")
    try:
        pem = _parse_rsa_key(private_key)
    except ValueError as e:
        return dashboard(request, db, walmart_error=str(e))
    if get_settings().walmart_provider == "affiliate":  # prove the credentials work before saving
        provider = WalmartAffiliateProvider(get_settings(), consumer_id=consumer_id, key_version=key_version,
                                            private_key_pem=pem, publisher_id=publisher_id or None)
        try:
            await provider.verify()
        except StoreError as e:
            return dashboard(request, db, walmart_error=str(e))
        finally:
            await provider.aclose()
    cred = db.scalar(select(WalmartCredential).where(WalmartCredential.user_id == user.id))
    if cred is None:
        cred = WalmartCredential(user_id=user.id)
        db.add(cred)
    cred.consumer_id, cred.key_version, cred.publisher_id = consumer_id, key_version, publisher_id or None
    cred.private_key_enc = encrypt(pem)
    db.commit()
    return dashboard(request, db, walmart_saved=True)


@router.post("/walmart/delete")
def delete_walmart(request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    cred = db.scalar(select(WalmartCredential).where(WalmartCredential.user_id == user.id))
    if cred:
        db.delete(cred)
        db.commit()
    return RedirectResponse("/dashboard", status_code=303)


# ---------- operator admin ----------
def _admin_or_none(request: Request, db: Session) -> User | None:
    user = current_user(request, db)
    return user if is_admin(user) else None


def _admin_page(request: Request, db: Session, user: User, message: str | None = None, error: str | None = None):
    rows = []
    for u in db.scalars(select(User).order_by(User.created_at)).all():
        plat = db.get(PlatformAccess, u.id)
        src = walmart_source(db, u)
        tiers = limits_for(db, u)
        rows.append({
            "user": u, "source": src, "platform": plat is not None, "verified": u.is_verified, "plan": u.plan,
            "custom": plat.limits if plat and plat.limits else "",
            "effective": ", ".join(f"{n} per {describe_window(sec)}" for sec, n in tiers),
        })
    pending = sum(1 for r in rows if not r["verified"])
    return render(request, "admin.html", user=user, rows=rows, message=message, error=error,
                  pending=pending, plans=list(PLANS))


@router.get("/admin")
def admin_home(request: Request, db: Session = Depends(get_db)):
    user = _admin_or_none(request, db)
    if not user:
        raise HTTPException(404, "Not found")
    return _admin_page(request, db, user)


@router.post("/admin/access")
def admin_access(request: Request, user_id: int = Form(...), action: str = Form(...), limits: str = Form(""),
                 plan: str = Form(""), csrf: str = Form(""), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    admin = _admin_or_none(request, db)
    if not admin:
        raise HTTPException(404, "Not found")
    target = db.get(User, user_id)
    if not target:
        return _admin_page(request, db, admin, error="No such user.")
    if action == "verify":  # the manual step while email isn't sent
        if not target.email_verified_at:
            target.email_verified_at = utcnow()
            db.commit()
        return _admin_page(request, db, admin, message=f"Verified {target.username} ({target.email}).")
    if action == "plan":
        if plan not in PLANS:
            return _admin_page(request, db, admin, error="Unknown plan.")
        target.plan = plan
        db.commit()
        return _admin_page(request, db, admin, message=f"{target.username} is now on the {PLANS[plan].name} plan.")
    limits = limits.strip().replace(" ", "")
    if action in ("grant", "save") and limits:
        try:
            parse_limits(limits)
        except (ValueError, TypeError):
            return _admin_page(request, db, admin, error="Limits must look like 120:5,3600:10,86400:20 "
                                                         "(window seconds:max requests, up to 1 day).")
    row = db.get(PlatformAccess, target.id)
    if action == "revoke":
        if row:
            db.delete(row)
        msg = f"Revoked platform access from {target.username}."
    elif action in ("grant", "save"):
        if row is None:
            row = PlatformAccess(user_id=target.id)
            db.add(row)
        row.limits = limits or None
        msg = f"{'Granted' if action == 'grant' else 'Updated'} {target.username}."
    else:
        return _admin_page(request, db, admin, error="Unknown action.")
    db.commit()
    return _admin_page(request, db, admin, message=msg)


# ---------- self-service rate limits ----------
LIMIT_ROWS = 3


def _limit_form(db: Session, user: User) -> dict:
    chosen = chosen_for(db, user)
    current = chosen if chosen is not None else default_chosen(db, user)
    rows = [{"count": n, "window": secs} for secs, n in current][:LIMIT_ROWS]
    rows += [{"count": "", "window": 3600}] * (LIMIT_ROWS - len(rows))
    return {
        "limit_rows": rows,
        "window_choices": WINDOW_CHOICES,
        "limits_custom": chosen is not None,
        "ceiling": ", ".join(f"{n} per {describe_window(secs)}" for secs, n in ceiling_for(db, user)),
    }


@router.post("/limits")
async def save_limits(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    check_csrf(request, str(form.get("csrf", "")))
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    row = db.get(UserLimits, user.id)
    if form.get("action") == "reset":
        if row:
            db.delete(row)
            db.commit()
        return dashboard(request, db, limits_message="Limits reset to the defaults.")

    allowed = {secs for secs, _ in WINDOW_CHOICES}
    tiers: dict[int, int] = {}
    for i in range(LIMIT_ROWS):
        count, window = str(form.get(f"count_{i}", "")).strip(), str(form.get(f"window_{i}", "")).strip()
        if not count:
            continue
        if not count.isdigit() or not 1 <= int(count) <= MAX_COUNT or not window.isdigit() or int(window) not in allowed:
            return dashboard(request, db, limits_error=f"Each limit needs a number from 1 to {MAX_COUNT:,} and a window.")
        secs = int(window)
        tiers[secs] = min(int(count), tiers.get(secs, int(count)))
    if not tiers:
        return dashboard(request, db, limits_error="Set at least one limit, or use Reset to go back to the defaults.")
    text = ",".join(f"{secs}:{n}" for secs, n in sorted(tiers.items()))
    if row is None:
        db.add(UserLimits(user_id=user.id, limits=text))
    else:
        row.limits = text
    db.commit()
    capped = [f"{n} per {describe_window(secs)}" for secs, n in ceiling_for(db, user)
              if secs in tiers and tiers[secs] > n]
    msg = "Limits saved."
    if capped:
        msg += " Your account maximum still applies: " + ", ".join(capped) + "."
    return dashboard(request, db, limits_message=msg)
