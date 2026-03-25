from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from .session import decode_session


def session_key(request: Request) -> str:
    """Key by user_id from session cookie; falls back to IP."""
    session_token = request.cookies.get("session")
    if session_token:
        try:
            user_id = decode_session(session_token)
            return f"user:{user_id}"
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)
