import logging
import os

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items")
auth_service = SpotifyAuthService()

# Hand the audio download and embedding to the external worker instead of doing it in
# this process (10.6). Default OFF: with it unset nothing about this file's behaviour
# changes, so the code can ship well before the worker machine exists.
#
# This must not be turned on before 10.5's attempt cap is deployed. In worker mode the
# stale branch returns in milliseconds rather than minutes, which would tighten the old
# failed-ingest loop from one pass every few minutes to one every few seconds — and the
# 2/minute limit below would become a new user's first experience.
#
# Read as a module global (not imported by value elsewhere) so a test can patch
# app.api.v1.songs.INGEST_WORKER_ENABLED and have it take effect.
INGEST_WORKER_ENABLED = os.getenv("INGEST_WORKER_ENABLED", "").lower() == "true"


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


async def _refresh_seed_snapshot(
    user: User, ingest_service: SpotifyIngestService, db: Session
) -> None:
    # Pull the user's current top tracks and write them over the seed snapshot. Kept as
    # one helper because both the worker branch and the in-process branch need it, and
    # because Phase 11's A6 replaces exactly this pair of calls when the Spotify login
    # is retired — one call site to rewrite instead of two.
    tracks = await auth_service.get_top_tracks(user.spotify_access_token)
    ingest_service.add_user_top_songs(tracks, user, db)


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
        if INGEST_WORKER_ENABLED:
            # Worker mode does no work here. It makes sure something is queued and
            # returns; the worker picks it up over the ingest API (10.6).
            #
            # The pending check is what stops a Spotify `me/top/tracks` call on every
            # request while the worker is still chewing. Stale means "no rows at all, or
            # rows still worth working on", so pending == 0 inside this branch means the
            # snapshot is genuinely empty and needs fetching; anything else is already
            # queued and re-fetching would only cost an API call.
            if ingest_service.pending_seed_count(user, db) == 0:
                await _refresh_seed_snapshot(user, ingest_service, db)
            if ingest_service.usable_seed_count(user, db) == 0:
                return RecsResponse(status="processing")
            # Otherwise fall through and dispatch from the seeds that are already done,
            # rather than making the user wait for the whole batch. This is the same
            # bargain the in-process path makes with on_first_success — with the caveat
            # that the tail is now minutes rather than seconds, so a dispatch generated
            # here can be locked in against a thin pool. Accepted: a thin dispatch today
            # beats no dispatch today, and tomorrow's has the full set.
            #
            # Deliberately no processing_users.add and no background task. The flag is
            # per-process and lost on every deploy, and with nothing in this process
            # clearing it there would be nothing to clear it — the permanent stuck
            # spinner that today's code does not have.
        else:
            await _refresh_seed_snapshot(user, ingest_service, db)
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
        failed = ingest_service.failed_seed_count(user, db)
        # WARNING, deliberately not ERROR (10.9). This logs an observed *state*, not a
        # transition: a user in this condition re-fetches on every dashboard mount and
        # every refresh, forever, so at ERROR it would raise a Sentry event each time
        # (DedupeIntegration only collapses events carrying exc_info). The once-per-seed
        # alarm is the terminal-retirement ERROR in _record_failure. This line is here so
        # that when you go looking, the logs say who hit the dead end and how wide it was.
        #
        # Logged only here, not in /status, which the frontend polls every 5 seconds.
        logger.warning(
            "Serving no_seeds to user %s (%d seed(s) failed terminally)", user.id, failed
        )
        return RecsResponse(status="no_seeds", unprocessed_seeds=failed)

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
