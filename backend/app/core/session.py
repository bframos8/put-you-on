import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET or not SESSION_SECRET.strip():
    raise RuntimeError(
        "SESSION_SECRET is not set. Define it in .env-backend (local) or the "
        "environment (deploy). No default is provided because a known secret "
        "would let anyone forge session cookies. Generate one with: "
        'python -c "import secrets; print(secrets.token_hex(32))"'
    )

_serializer = URLSafeTimedSerializer(SESSION_SECRET)

# 30 days
SESSION_MAX_AGE = 60 * 60 * 24 * 30


def create_session(user_id: int) -> str:
    return _serializer.dumps(user_id, salt="session")


def decode_session(token: str) -> int | None:
    try:
        return _serializer.loads(token, salt="session", max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
