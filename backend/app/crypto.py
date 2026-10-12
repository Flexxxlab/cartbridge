import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    material = s.encryption_key or s.secret_key
    # Any string works: derive a valid 32-byte Fernet key from it.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest()))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("Cannot decrypt stored credentials (ENCRYPTION_KEY/SECRET_KEY changed?)") from e
