from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...db.database import get_db
from ...db.models import User, Song
from ...core.dependencies import get_current_user
from ...core.limiter import limiter, session_key
from ...schemas.song import SongResponse, RecsResponse
from ...services.spotify_auth_service import SpotifyAuthService
from ...services.spotify_ingest_service import SpotifyIngestService, get_ingest_service

router = APIRouter(prefix="/items")
auth_service = SpotifyAuthService()


@router.get("/song_recs/")
@limiter.limit("2/minute", key_func=session_key)
async def get_recs(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    ingest_service: SpotifyIngestService = Depends(get_ingest_service),
) -> RecsResponse:
    user = await auth_service.refresh_tokens(db, user)

    if ingest_service.snapshot_is_stale(user, db):
        tracks = await auth_service.get_top_tracks(user.spotify_access_token)
        genre_map = await auth_service.get_track_genres(tracks, user.spotify_access_token)
        ingest_service.add_user_top_songs(tracks, user, db, genre_map=genre_map)
        try:
            ingest_service.process_top_tracks(user, db)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    query_song, results = ingest_service.query_recommendations(user, db)
    return RecsResponse(
        query_title=query_song.title,
        query_artist=query_song.artist_name,
        recommendations=[SongResponse.from_song(s) for s in results],
    )
