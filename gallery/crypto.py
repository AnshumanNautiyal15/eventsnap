"""Encryption for secrets kept in the database (Google sign-in tokens)."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

PREFIX = "enc:"


def _fernet():
    key = settings.DATA_ENCRYPTION_KEY
    if not key:
        # Fallback: derive from SECRET_KEY. Fine to start with; set DATA_ENCRYPTION_KEY to decouple them.
        key = base64.urlsafe_b64encode(hashlib.sha256(f"weddingsnap|{settings.SECRET_KEY}".encode()).digest())
    return Fernet(key)


def encrypt(value):
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value):
    if not value or not value.startswith(PREFIX):
        return value  # stored before encryption existed
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return ""  # key changed: treated as "not connected", the photographer reconnects Google
