from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env-backend")

from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .db.database import engine
from .db.models import Base
from .services.spotify_ingest_service import SpotifyIngestService
from .api.v1 import auth, songs
from .core.limiter import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    app.state.ingest_service = SpotifyIngestService()
    yield
    engine.dispose()


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router, prefix = "/api/v1")
app.include_router(songs.router, prefix = "/api/v1")
