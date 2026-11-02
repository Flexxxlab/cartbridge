"""One-off: send a verification email to existing unverified users. Run on the server:

  docker exec cartbridge python -m app.send_verifications              dry run (default): count + masked emails
  docker exec cartbridge python -m app.send_verifications --dry-run    same
  docker exec cartbridge python -m app.send_verifications --send       really send (needs RESEND_API_KEY)

Each send issues a fresh 24 h single-use link (older unused verification links stop working) and is logged
with the user id and a masked address. Users who got a verification link in the last 24 h are skipped, so
re-running (or restarting after a crash) never mails anyone twice; a failed send is retried on the next run. Never prints tokens or the API key.
"""
import argparse
import logging
import sys
import time

from .auth_email import send_verification_now, unverified_users
from .config import get_settings
from .db import SessionLocal, engine
from .emailer import mask_email
from .migrate import migrate

log = logging.getLogger("cartbridge.send_verifications")
PAUSE_SECONDS = 0.6  # Resend allows 2 requests/second


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.send_verifications")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list who would get an email (default)")
    mode.add_argument("--send", action="store_true", help="actually send the emails")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    migrate(engine)
    with SessionLocal() as db:
        users = unverified_users(db)
        skipped = len(unverified_users(db, skip_recent=False)) - len(users)
        print(f"{len(users)} unverified active user(s) to mail; {skipped} skipped (got a link in the last "
              f"{get_settings().email_token_ttl_hours} h).")
        if not a.send:
            for u in users:
                print(f"  would send: user {u.id}  {mask_email(u.email)}")
            print("Dry run: nothing sent. Use --send to send.")
            return 0
        if not get_settings().resend_api_key:
            print("RESEND_API_KEY is not set; refusing to send.", file=sys.stderr)
            return 2
        sent = failed = 0
        for u in users:
            ok = send_verification_now(db, u)
            sent, failed = sent + ok, failed + (not ok)
            print(f"  {'sent' if ok else 'FAILED'}: user {u.id}  {mask_email(u.email)}", flush=True)
            time.sleep(PAUSE_SECONDS)
        print(f"Done: {sent} sent, {failed} failed.")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
