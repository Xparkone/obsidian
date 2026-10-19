from __future__ import annotations

import hashlib
import hmac
import secrets


KEY_PREFIX_LENGTH = 22


def issue_api_key() -> str:
    return "aegis_" + secrets.token_urlsafe(32)


def api_key_prefix(api_key: str) -> str:
    """Return the non-secret lookup prefix stored with a principal."""
    return api_key[:KEY_PREFIX_LENGTH]


def hash_api_key(api_key: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(api_key.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_api_key(api_key: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split("$", 1)
        expected = hashlib.scrypt(api_key.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# Passwords use the same memory-hard primitive as API keys.  Keep separate
# names at the call sites so it is clear which credential is being handled.
def hash_password(password: str, salt: bytes | None = None) -> str:
    return hash_api_key(password, salt)


def verify_password(password: str, encoded: str) -> bool:
    return verify_api_key(password, encoded)


def issue_session_token() -> str:
    return "aegis_session_" + secrets.token_urlsafe(32)
