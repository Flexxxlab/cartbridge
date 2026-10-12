"""Password hashing (stdlib scrypt), API keys and one-time tokens."""
import base64
import hashlib
import hmac
import os
import secrets

_N, _R, _P = 2**14, 8, 1
API_KEY_PREFIX = "cb_"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        expected = _unb64(dk)
        got = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(got, expected)
    except (ValueError, TypeError):
        return False


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, display_prefix, key_hash). Only the hash is stored."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:11], sha256_hex(raw)


def new_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash) for email verification links."""
    raw = secrets.token_urlsafe(32)
    return raw, sha256_hex(raw)


def new_csrf() -> str:
    return secrets.token_urlsafe(24)
