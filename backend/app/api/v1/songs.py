from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...core.daily import DAILY_LIMIT_BYPASS, next_midnight_pst
from ...db.database import get_db
from ...db.models import Song, User, UserTopSong
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
            # Generate today's dispatch as soon as the first top track finishes
            # processing and let the frontend's /status poll flip to "ready".
            # The remaining top tracks keep processing in the background so
            # tomorrow's dispatch already has fresh query candidates.
            def unblock():
                ingest_service.query_recommendations(user, db)
                processing_users.discard(user_id)
            ingest_service.process_top_tracks(user, db, on_first_success=unblock)
    finally:
        processing_users.discard(user_id)
        db.close()


def _dispatch_response(
    query_song: Song, results: list[Song], locked: bool, unprocessed_seeds: int = 0
) -> RecsResponse:
    return RecsResponse(
        status="ready",
        query_title=query_song.title,
        query_artist=query_song.artist_name,
        recommendations=[SongResponse.from_song(s) for s in results],
        locked_for_today=locked,
        next_dispatch_at=next_midnight_pst().isoformat() if locked else None,
        unprocessed_seeds=unprocessed_seeds,
    )


@router.get("/status")
@limiter.limit("30/minute", key_func=session_key)
async def get_status(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    ingest_service: SpotifyIngestService = Depends(get_ingest_service),
):
    # Derived from the database, not only from app.state.processing_users (10.5).
    # That set is per-process and per-container: it is lost on every deploy, and a
    # second uvicorn worker would answer "ready" for an ingest it never started.
    #
    # The important part is what "ready" means. It must mean "a dispatch can be
    # produced", NOT "the queue is empty". Conflating those is what produced the
    # re-queue loop: with every seed failed the queue was empty, /status said ready,
    # the frontend asked for recs, the snapshot was still stale, and the whole failing
    # ingest ran again.
    if user.id in request.app.state.processing_users:
        return {"status": "processing"}
    if ingest_service.usable_seed_count(user, db) > 0:
        return {"status": "ready"}
    if ingest_service.snapshot_is_stale(user, db):
        # Work is genuinely outstanding — either nothing has been fetched yet, or seeds
        # are waiting on an ingest that is not running in this process.
        return {"status": "processing"}
    # Seeds exist, none are usable, and none are still eligible to retry. Terminal:
    # keep polling and the spinner never stops.
    return {"status": "no_seeds"}


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

    # Row-level lock on the user serializes concurrent dispatch generation
    # so a single user can't race their way to more than 10 recs per day.
    db.query(User).filter(User.id == user.id).with_for_update().one()

    if not DAILY_LIMIT_BYPASS:
        existing = ingest_service.get_todays_dispatch(user, db)
        if existing:
            query_song, results = existing
            db.commit()
            return _dispatch_response(query_song, results, locked=True)

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

    # Guard before calling query_recommendations (10.5). The snapshot can now be
    # not-stale while holding zero usable seeds — every one failed terminally — and in
    # that state query_recommendations has no seed to pick and raises. Returning an
    # honest terminal status beats a 500 the frontend silently swallows.
    if ingest_service.usable_seed_count(user, db) == 0:
        return RecsResponse(
            status="no_seeds",
            unprocessed_seeds=ingest_service.failed_seed_count(user, db),
        )

    query_song, results = ingest_service.query_recommendations(user, db)
    return _dispatch_response(
        query_song,
        results,
        locked=not DAILY_LIMIT_BYPASS,
        unprocessed_seeds=ingest_service.failed_seed_count(user, db),
    )


@router.get("/top_tracks/")
@limiter.limit("30/minute", key_func=session_key)
def get_top_tracks(
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
    # All rows in one snapshot share a snapshot_at; max() is robust if a future
    # change ever mixes snapshots. None when there are no rows yet.
    last_synced_at = max((r.snapshot_at for r in rows if r.snapshot_at), default=None)
    return TopTracksResponse(
        tracks=[TopTrackItem.from_user_top_song(r) for r in rows],
        last_synced_at=last_synced_at,
    )
