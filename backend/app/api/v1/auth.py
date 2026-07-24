import logging
import os
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ...db.database import get_db
from ...db.models import User
from ...services.spotify_auth_service import SpotifyAuthService
from ...core.session import create_session
from ...core.dependencies import get_current_user
from ...core.limiter import limiter, session_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")
auth_service = SpotifyAuthService()

OAUTH_STATE_TTL_SECONDS = int(os.getenv("OAUTH_STATE_TTL_SECONDS", "600"))


def get_frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "https://127.0.0.1:3000/dashboard")


def _sweep_expired_states(oauth_states: dict, now: float) -> None:
    """Evict OAuth states older than the TTL so the dict can't grow unbounded."""
    expired = [s for s, ts in oauth_states.items() if now - ts > OAUTH_STATE_TTL_SECONDS]
    for s in expired:
        del oauth_states[s]


@router.get("/spotify/login")
@limiter.limit("20/minute")
async def spotify_login(request: Request):
    auth_url, state = auth_service.get_auth_url()
    oauth_states = request.app.state.oauth_states
    _sweep_expired_states(oauth_states, time.time())
    oauth_states[state] = time.time()
    return RedirectResponse(url=auth_url)


@router.get("/spotify/callback")
@limiter.limit("10/minute")
async def spotify_callback(request: Request, code: str = None, state: str = None, error: str = None, db: Session = Depends(get_db)):
    frontend_url = get_frontend_url()

    if error:
        return RedirectResponse(url=f"{frontend_url}?error={error}")

    oauth_states = request.app.state.oauth_states
    if not state or state not in oauth_states:
        return RedirectResponse(url=f"{frontend_url}?error=state_mismatch")
    issued_at = oauth_states.pop(state)
    if time.time() - issued_at > OAUTH_STATE_TTL_SECONDS:
        return RedirectResponse(url=f"{frontend_url}?error=state_mismatch")

    try:
        token_data = await auth_service.exchange_code(code)
        profile = await auth_service.get_spotify_profile(token_data["access_token"])
        user = await auth_service.upsert_user(db, token_data, profile)
    except Exception as e:
        logger.error("Spotify callback failed: %s", type(e).__name__)
        return RedirectResponse(url=f"{frontend_url}?error=auth_failed")

    response = RedirectResponse(url=frontend_url)
    response.set_cookie(
        key="session",
        value=create_session(user.id),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response


@router.get("/me")
@limiter.limit("60/minute", key_func=session_key)
async def me(request: Request, user: User = Depends(get_current_user)):
    return {"display_name": user.display_name, "email": user.email}


@router.post("/logout")
@limiter.limit("10/minute", key_func=session_key)
async def logout(request: Request):
    response = Response(status_code=204)
    response.delete_cookie("session", secure=True, samesite="lax")
    return response
