from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...db.database import get_db
from ...db.models import User, Song, UserTopSong
from ...core.dependencies import get_current_user
from ...core.limiter import limiter, session_key
from ...schemas.song import SongResponse, RecsResponse, TopTrackItem, TopTracksResponse
from ...services.spotify_auth_service import SpotifyAuthService
from ...services.spotify_ingest_service import SpotifyIngestService, get_ingest_service

router = APIRouter(prefix="/items")
auth_service = SpotifyAuthService()


def _run_process_top_tracks(user_id: int, ingest_service: SpotifyIngestService, db: Session, processing_users: set):
    try:
        from ...db.models import User as UserModel
        user = db.query(UserModel).filter(UserModel.id == user_id).first()
        if user:
            ingest_service.process_top_tracks(user, db)
    finally:
        processing_users.discard(user_id)
        db.close()


@router.get("/status")
@limiter.limit("30/minute", key_func=session_key)
async def get_status(
    request: Request,
    user: User = Depends(get_current_user),
):
    processing_users = request.app.state.processing_users
    if user.id in processing_users:
        return {"status": "processing"}
    return {"status": "ready"}


@router.get("/song_recs/")
@limiter.limit("2/minute", key_func=session_key)
async def get_recs(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    ingest_service: SpotifyIngestService = Depends(get_ingest_service),
) -> RecsResponse:
    user = await auth_service.refresh_tokens(db, user)
    processing_users = request.app.state.processing_users

    if user.id in processing_users:
        return RecsResponse(status="processing")

    if ingest_service.snapshot_is_stale(user, db):
        tracks = await auth_service.get_top_tracks(user.spotify_access_token)
        ingest_service.add_user_top_songs(tracks, user, db)
        processing_users.add(user.id)

        from ...db.database import SessionLocal
        background_db = SessionLocal()
        background_tasks.add_task(
            _run_process_top_tracks, user.id, ingest_service, background_db, processing_users
        )
        return RecsResponse(status="processing")

    query_song, results = ingest_service.query_recommendations(user, db)
    return RecsResponse(
        status="ready",
        query_title=query_song.title,
        query_artist=query_song.artist_name,
        recommendations=[SongResponse.from_song(s) for s in results],
    )


@router.get("/top_tracks/")
@limiter.limit("30/minute", key_func=session_key)
async def get_top_tracks(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TopTracksResponse:
    rows = (
        db.query(UserTopSong)
        .filter(UserTopSong.user_id == user.id)
        .order_by(UserTopSong.id.asc())
        .limit(10)
        .all()
    )
    return TopTracksResponse(tracks=[TopTrackItem.from_user_top_song(r) for r in rows])
