import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env-backend")

from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .core.daily import DAILY_LIMIT_BYPASS
from .db.database import engine
from .db.models import Base
from .services.spotify_ingest_service import SpotifyIngestService
from .api.v1 import auth, health, songs
from .core.limiter import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    app.state.ingest_service = SpotifyIngestService()
    app.state.oauth_states = {}
    app.state.processing_users = set()
    if DAILY_LIMIT_BYPASS:
        print(
            "WARNING: DAILY_LIMIT_BYPASS=true — daily dispatch limit is DISABLED. Do not enable in production.",
            flush=True,
        )
    yield
    engine.dispose()


_cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "https://127.0.0.1:3000")
ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()]

# Emit HSTS only where TLS terminates in front of the app (the app itself sits
# behind the nginx :443 proxy on plain HTTP, so it can't infer the real scheme).
ENABLE_HSTS = os.getenv("ENABLE_HSTS", "").lower() == "true"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

class SecurityHeadersMiddleware:
    """Pure ASGI middleware that stamps baseline security headers onto every
    response. Implemented at the ASGI layer (not BaseHTTPMiddleware) because the
    latter drops the response body when a route attaches a BackgroundTask under
    Starlette 0.27 — which the stale-snapshot `/song_recs/` path does."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers.setdefault(key, value)
                if ENABLE_HSTS:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(health.router)
app.include_router(auth.router, prefix = "/api/v1")
app.include_router(songs.router, prefix = "/api/v1")
