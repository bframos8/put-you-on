from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db.database import get_db

# Mounted at the root (no /api/v1 prefix) so the compose HEALTHCHECK, nginx
# upstream check, and the deploy health gate can hit a stable /health path.
# Unauthenticated and not rate-limited on purpose: these are infra probes.
router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health():
    """Liveness: the process is up and serving. No dependencies checked."""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness: liveness plus a cheap round-trip to the database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail={"status": "unavailable"})
    return {"status": "ready"}
