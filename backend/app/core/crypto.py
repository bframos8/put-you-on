import os

from cryptography.fernet import Fernet, MultiFernet

# Comma-separated Fernet keys. The first encrypts new values; any listed key can
# decrypt (so a key can be rotated by prepending a new one, re-encrypting, then
# dropping the old). Fail fast at import — a missing/known key makes at-rest
# encryption pointless, so we never silently store plaintext (mirrors session.py).
_keys_raw = os.getenv("TOKEN_ENCRYPTION_KEYS")
if not _keys_raw or not _keys_raw.strip():
    raise RuntimeError(
        "TOKEN_ENCRYPTION_KEYS is not set. Define it in .env-backend (local) or the "
        "environment (deploy) — and export it before `alembic upgrade head`, since the "
        "models import this module. It holds one or more comma-separated Fernet keys; "
        "the first encrypts new values and any of them can decrypt (key rotation). No "
        "default is provided because a known key would make at-rest encryption useless. "
        'Generate one with: python -c "from cryptography.fernet import Fernet; '
        'print(Fernet.generate_key().decode())"'
    )

_keys = [k.strip() for k in _keys_raw.split(",") if k.strip()]
_fernet = MultiFernet([Fernet(k) for k in _keys])


def encrypt(value: str) -> str:
    """Encrypt a UTF-8 string to URL-safe base64 ciphertext (str)."""
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt ciphertext produced by encrypt() back to the original string."""
    return _fernet.decrypt(value.encode()).decode()
