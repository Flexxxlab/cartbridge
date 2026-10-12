"""Operator commands. Run on the server: docker exec cartbridge python -m app.admin <command>

  grant <username> [--limit SECONDS:COUNT ...]   let this account use CartBridge's own Walmart credentials
        e.g. --limit 120:5 --limit 3600:10 --limit 86400:20  (5 per 2 min, 10 per hour, 20 per day)
  revoke <username>                         remove that access
  list                                      show accounts with platform access
  passwd <username>                         set a new password (prompts; nothing is echoed)
"""
import argparse
import sys

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import PlatformAccess, User
from .ratelimit import parse_limits
from .security import hash_password


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
    pw = sub.add_parser("passwd")
    pw.add_argument("username")
    a = ap.parse_args(argv)

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if a.cmd == "list":
            rows = db.execute(select(User.username, PlatformAccess.limits)
                              .join(PlatformAccess, PlatformAccess.user_id == User.id)).all()
            for u, lim in rows:
                print(f"{u}\t{lim or 'default limits'}")
            return 0
        user = db.scalar(select(User).where(User.username == a.username))
        if not user:
            print(f"No such user: {a.username}", file=sys.stderr)
            return 1
        if a.cmd == "passwd":
            import getpass
            new = getpass.getpass("New password (min 8 chars): ")
            if len(new) < 8 or new != getpass.getpass("Repeat: "):
                print("Passwords must match and be at least 8 characters.", file=sys.stderr)
                return 2
            user.password_hash = hash_password(new)
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
