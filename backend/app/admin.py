"""Operator commands. Run on the server: docker exec cartbridge python -m app.admin <command>

  grant <username> [--limit SECONDS:COUNT ...]   let this account use CartBridge's own Walmart credentials
        e.g. --limit 120:5 --limit 3600:10 --limit 86400:20  (5 per 2 min, 10 per hour, 20 per day)
  revoke <username>                         remove that access
  list                                      show accounts with platform access
  passwd <username>                         set a new password (prompts; nothing is echoed)
  users                                     all accounts: verified?, plan, keys, requests this month
  keys                                      active API keys: prefix, owner, last used (never the key itself)
  verify <username|email>                   mark the email verified (manual step while email isn't sent)
  plan <username> <free|pro>                change the account's plan
  move-key <key-prefix> <username> [--force] give an API key (and its platform grant + limits) to another account;
                                            the key itself is unchanged, so clients keep working
  delete-user <username> --yes [--force]    delete the account and everything it owns (irreversible);
                                            refuses if it owns a platform grant or active key unless --force
"""
import argparse
import sys

from sqlalchemy import delete, func, select

from .db import SessionLocal, engine
from .migrate import migrate
from .models import (ApiKey, CartRequestLog, EmailToken, PlatformAccess, UsageMonthly, User, UserLimits,
                     WalmartCredential, utcnow)
from .plans import PLANS
from .ratelimit import parse_limits
from .security import hash_password


def _users(db) -> int:
    from .ratelimit import month_key
    month = month_key(utcnow())
    print("id\tusername\temail\tverified\tplan\tkeys\tplatform\tmonth_requests\tcreated")
    for u in db.scalars(select(User).order_by(User.id)).all():
        keys = db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == u.id, ApiKey.revoked_at.is_(None)))
        used = db.get(UsageMonthly, (u.id, month))
        print(f"{u.id}\t{u.username}\t{u.email}\t{'yes' if u.is_verified else 'NO'}\t{u.plan}\t{keys}\t"
              f"{'yes' if db.get(PlatformAccess, u.id) else '-'}\t{used.count if used else 0}\t{u.created_at:%Y-%m-%d}")
    return 0


def _verify(db, who: str) -> int:
    user = db.scalar(select(User).where((User.username == who) | (User.email == who.lower())))
    if not user:
        print(f"No such user or email: {who}", file=sys.stderr)
        return 1
    if not user.email_verified_at:
        user.email_verified_at = utcnow()
        db.commit()
    print(f"Verified {user.username} ({user.email})")
    return 0


def _move_key(db, prefix: str, username: str, force: bool = False) -> int:
    target = db.scalar(select(User).where(User.username == username))
    keys = db.scalars(select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))).all()
    if not target or len(keys) != 1:
        print("Need an existing target user and exactly one active key with that prefix "
              f"(found {len(keys)}).", file=sys.stderr)
        return 1
    key = keys[0]
    old = db.get(User, key.user_id)
    if old.id == target.id:
        print("Key already belongs to that account.")
        return 0
    if db.get(PlatformAccess, target.id) and not force:
        print(f"Aborting: {target.username} already has platform access, so {old.username}'s grant and limits "
              "would NOT move with the key. Check `list`; rerun with --force to move only the key.", file=sys.stderr)
        return 2
    key.user_id = target.id
    # The platform grant and any self-chosen limits travel with the key's purpose.
    for model in (PlatformAccess, UserLimits):
        row = db.get(model, old.id)
        if row and not db.get(model, target.id):
            row.user_id = target.id
    db.commit()
    print(f"Moved key {prefix}... from {old.username} to {target.username} (key value unchanged)")
    return 0


def _delete_user(db, user: User, confirmed: bool, force: bool = False) -> int:
    if not confirmed:
        print("Refusing without --yes. This deletes the account and everything it owns.", file=sys.stderr)
        return 2
    grant = db.get(PlatformAccess, user.id)
    keys = db.scalars(select(ApiKey.prefix).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))).all()
    if (grant or keys) and not force:
        owns = (["a platform grant"] if grant else []) + ([f"{len(keys)} active API key(s): {', '.join(keys)}"] if keys else [])
        print(f"Refusing: {user.username} owns {' and '.join(owns)}. Move the key first (move-key), "
              "or pass --force to delete anyway.", file=sys.stderr)
        return 2
    for model in (EmailToken, CartRequestLog, WalmartCredential, PlatformAccess, UserLimits, UsageMonthly, ApiKey):
        db.execute(delete(model).where(model.user_id == user.id))  # SQLite doesn't enforce ON DELETE CASCADE
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
    print(f"Deleted {user.username}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grant")
    g.add_argument("username")
    g.add_argument("--limit", action="append", metavar="SECONDS:COUNT",
                   help="repeatable; replaces this account's limits (default: server defaults)")
    r = sub.add_parser("revoke")
    r.add_argument("username")
    sub.add_parser("list")
    sub.add_parser("users")
    sub.add_parser("keys")
    v = sub.add_parser("verify")
    v.add_argument("who", metavar="username|email")
    pl = sub.add_parser("plan")
    pl.add_argument("username")
    pl.add_argument("plan", choices=sorted(PLANS))
    mk = sub.add_parser("move-key")
    mk.add_argument("prefix", help="the key prefix shown in the dashboard, e.g. cb_AbC123xy")
    mk.add_argument("username", help="the account that should own the key")
    mk.add_argument("--force", action="store_true", help="move even if a platform grant exists on either account")
    du = sub.add_parser("delete-user")
    du.add_argument("username")
    du.add_argument("--yes", action="store_true", help="required; there is no undo")
    du.add_argument("--force", action="store_true", help="also delete an account that owns a platform grant or active key")
    pw = sub.add_parser("passwd")
    pw.add_argument("username")
    a = ap.parse_args(argv)

    migrate(engine)
    with SessionLocal() as db:
        if a.cmd == "list":
            rows = db.execute(select(User.username, PlatformAccess.limits)
                              .join(PlatformAccess, PlatformAccess.user_id == User.id)).all()
            for u, lim in rows:
                print(f"{u}\t{lim or 'default limits'}")
            return 0
        if a.cmd == "users":
            return _users(db)
        if a.cmd == "keys":
            print("prefix\towner\tname\tcreated\tlast_used")
            for k, u in db.execute(select(ApiKey, User).join(User, User.id == ApiKey.user_id)
                                   .where(ApiKey.revoked_at.is_(None)).order_by(ApiKey.id)).all():
                print(f"{k.prefix}\t{u.username}\t{k.name}\t{k.created_at:%Y-%m-%d}\t"
                      f"{k.last_used_at:%Y-%m-%d %H:%M}" if k.last_used_at else
                      f"{k.prefix}\t{u.username}\t{k.name}\t{k.created_at:%Y-%m-%d}\tnever")
            return 0
        if a.cmd == "verify":
            return _verify(db, a.who)
        if a.cmd == "move-key":
            return _move_key(db, a.prefix, a.username, a.force)
        user = db.scalar(select(User).where(User.username == a.username))
        if not user:
            print(f"No such user: {a.username}", file=sys.stderr)
            return 1
        if a.cmd == "plan":
            user.plan = a.plan
            db.commit()
            print(f"{user.username} is now on the {PLANS[a.plan].name} plan")
            return 0
        if a.cmd == "delete-user":
            return _delete_user(db, user, a.yes, a.force)
        if a.cmd == "passwd":
            import getpass
            new = getpass.getpass("New password (min 8 chars): ")
            if len(new) < 8 or new != getpass.getpass("Repeat: "):
                print("Passwords must match and be at least 8 characters.", file=sys.stderr)
                return 2
            user.password_hash = hash_password(new)
            user.session_version += 1  # log out existing browser sessions
            db.commit()
            print(f"Password updated for {user.username}")
            return 0
        row = db.get(PlatformAccess, user.id)
        if a.cmd == "grant":
            if row is None:
                row = PlatformAccess(user_id=user.id)
                db.add(row)
            if a.limit:
                try:
                    parse_limits(",".join(a.limit))
                except ValueError as e:
                    print(f"Invalid --limit: {e}", file=sys.stderr)
                    return 2
                row.limits = ",".join(a.limit)
            print(f"Granted platform access to {user.username} ({row.limits or 'default limits'})")
        else:
            if row:
                db.delete(row)
            print(f"Revoked platform access from {user.username}")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
