import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-in-production")
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
