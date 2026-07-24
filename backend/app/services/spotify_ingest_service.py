import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import Request
from sqlalchemy import func, or_, text

import essentia
import numpy as np
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs
from sqlalchemy.orm import Session, selectinload

from ..core.daily import today_pst
from ..db.models import Album, Song, User, UserRecommendation, UserTopSong
from .audio_genre_classifier import AudioGenreClassifier

logger = logging.getLogger(__name__)

essentia.log.warningActive = False

GRAPH_FILE = Path(__file__).resolve().parents[1] / "models" / "discogs-effnet-bs64-1.pb"
DOWNLOADS_DIR = Path(__file__).parent / "downloads"
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg"}


class SpotifyIngestService:
    def __init__(self):
        DOWNLOADS_DIR.mkdir(exist_ok=True)
        self.model = TensorflowPredictEffnetDiscogs(
            graphFilename=str(GRAPH_FILE), output="PartitionedCall:1"
        )
        self.genre_classifier = AudioGenreClassifier()

    def ingest(self, spotify_url: str, db: Session) -> Song:
        audio_path = self._download(spotify_url)
        try:
            audio = self._load_audio(audio_path)
            embedding = self._embed(audio)
            song = self._write_to_db(audio_path, embedding, db)
        finally:
            self._cleanup(audio_path)
        return song

    def _download(self, spotify_url: str) -> Path:
        # Each download gets its own temp dir under DOWNLOADS_DIR so concurrent
        # ingests can't pick up each other's files (mkdtemp is atomic/unique).
        # Because the dir starts empty, we find our file by globbing only it — no
        # whole-DOWNLOADS_DIR before/after diff. An empty result still means the
        # download produced no audio (the old line-58 success check).
        job_dir = Path(tempfile.mkdtemp(prefix="ingest_", dir=DOWNLOADS_DIR))
        try:
            subprocess.run(
                ["spotdl", "--no-cache", "--format", "mp3", "--bitrate", "320k",
                "--client-id", os.getenv("SPOTIFY_CLIENT_ID"),
                "--client-secret", os.getenv("SPOTIFY_CLIENT_SECRET"),
                "--output", str(job_dir),
                spotify_url],
                check=True,
            )
            audio_files = [
                f for f in job_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
            ]
            if not audio_files:
                raise FileNotFoundError(f"spotdl produced no audio file for {spotify_url}")
            return audio_files[0]
        except Exception:
            # Callers only _cleanup a returned path, so a failed download must
            # clean up its own temp dir here or it leaks.
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

    def _load_audio(self, audio_path: Path) -> np.ndarray:
        return MonoLoader(
            filename=str(audio_path), sampleRate=16000, resampleQuality=4
        )()

    def _embed(self, audio: np.ndarray) -> np.ndarray:
        # Mirrors the data_pipeline SongEmbedder._embed_song guard (single
        # source of truth by convention): raise on degenerate audio instead of
        # returning a garbage mean. Keep this guard in sync across both apps.
        frame_embeddings = self.model(audio)
        if not isinstance(frame_embeddings, np.ndarray) or frame_embeddings.ndim == 0 or len(frame_embeddings) == 0:
            raise ValueError(f"Model returned no frames — audio may be too short ({len(audio) / 16000:.2f}s)")
        return frame_embeddings.mean(axis=0)

    def _write_to_db(self, audio_path: Path, embedding: np.ndarray, db: Session) -> Song:
        song = Song(
            title=audio_path.stem,
            embedding=embedding.tolist(),
            is_candidate=False,
        )
        db.add(song)
        db.commit()
        db.refresh(song)
        return song

    def _cleanup(self, audio_path: Path) -> None:
        # Remove the per-download temp dir (the direct child of DOWNLOADS_DIR that
        # _download created), so spotdl's stray files go too. Guard hard against
        # ever rmtree-ing DOWNLOADS_DIR itself; fall back to file-only removal.
        try:
            top = DOWNLOADS_DIR / audio_path.relative_to(DOWNLOADS_DIR).parts[0]
            if top != DOWNLOADS_DIR and top.is_dir():
                shutil.rmtree(top, ignore_errors=True)
                return
        except (ValueError, IndexError):
            pass
        if audio_path.exists():
            os.remove(audio_path)

    def add_user_top_songs(self, tracks: list[dict], user: User, db: Session) -> None:
        db.query(UserTopSong).filter(UserTopSong.user_id == user.id).delete()
        snapshot_at = datetime.now()
        track_ids = [track["id"] for track in tracks]
        existing_by_track = {
            s.spotify_track_id: s
            for s in db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
        } if track_ids else {}
        for track in tracks:
            spotify_track_id = track["id"]
            song = existing_by_track.get(spotify_track_id)
            db.add(UserTopSong(
                user_id=user.id,
                song_id=song.id if song else None,
                spotify_track_id=spotify_track_id,
                spotify_url=track["external_urls"]["spotify"],
                image_url=track["album"]["images"][0]["url"],
                artist_name=track["artists"][0]["name"],
                track_title=track["name"],
                album_title=track["album"]["name"],
                duration_ms=track.get("duration_ms"),
                genre=song.genre if song else None,
                snapshot_at=snapshot_at,
            ))
        db.commit()

    def process_top_tracks(
        self,
        user: User,
        db: Session,
        on_first_success: Callable[[], None] | None = None,
    ) -> None:
        unprocessed = (
            db.query(UserTopSong)
            .filter(
                UserTopSong.user_id == user.id,
                or_(UserTopSong.song_id == None, UserTopSong.genre == None),
            )
            .all()
        )
        # Snapshot existing Songs once (track ids are unique, so no in-loop
        # insert invalidates the snapshot) instead of one query per track.
        track_ids = [top_song.spotify_track_id for top_song in unprocessed]
        existing_by_track = {
            s.spotify_track_id: s
            for s in db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
        } if track_ids else {}

        first_done = False
        for top_song in unprocessed:
            existing = existing_by_track.get(top_song.spotify_track_id)
            success = False

            # Fast path: an existing Song already carries a genre — reuse it.
            if existing and existing.genre:
                top_song.song_id = existing.id
                top_song.genre = existing.genre
                db.commit()
                success = True
            else:
                logger.info("Processing: %s | %s", top_song.track_title, top_song.spotify_url)
                try:
                    audio_path = self._download(top_song.spotify_url)
                except Exception as e:
                    logger.warning("Skipping %s: download failed: %s", top_song.track_title, e)
                    continue

                logger.info("Downloaded to: %s", audio_path)
                try:
                    audio = self._load_audio(audio_path)
                    genre = self.genre_classifier.classify(audio)
                    top_song.genre = genre

                    if existing:
                        top_song.song_id = existing.id
                        existing.genre = genre
                    else:
                        embedding = self._embed(audio)
                        song = Song(
                            title=top_song.track_title,
                            artist_name=top_song.artist_name,
                            album_title=top_song.album_title,
                            spotify_track_id=top_song.spotify_track_id,
                            genre=genre,
                            embedding=embedding.tolist(),
                            is_candidate=False,
                        )
                        db.add(song)
                        db.flush()
                        top_song.song_id = song.id
                    db.commit()
                    success = True
                except Exception as e:
                    db.rollback()
                    logger.warning("Skipping %s: processing failed: %s", top_song.track_title, e)
                finally:
                    self._cleanup(audio_path)

            if success and not first_done and on_first_success:
                first_done = self._fire_first_success(on_first_success, db)

    @staticmethod
    def _fire_first_success(callback, db: Session) -> bool:
        # Roll back on failure so any in-memory changes the callback made
        # (e.g. UserTopSong.used_as_query=True inside query_recommendations)
        # don't bleed into the next iteration's commit.
        try:
            callback()
            return True
        except Exception as e:
            db.rollback()
            logger.warning("on_first_success callback failed; will retry on next song: %s", e)
            return False

    def snapshot_is_stale(self, user: User, db: Session) -> bool:
        # "Stale" means the snapshot needs a (re)build — it's empty, or a prior
        # ingest didn't finish processing every row. Pool exhaustion (all rows
        # used as query seeds) is deliberately NOT stale: query_recommendations
        # recycles the existing candidates instead of re-fetching from Spotify (A6).
        result = db.query(
            func.count().label("total"),
            func.count(UserTopSong.song_id).label("processed"),
        ).filter(UserTopSong.user_id == user.id).one()

        if result.total == 0:
            return True
        return result.processed < result.total

    @staticmethod
    def _dedupe_by_artist(pool: list, limit: int) -> list[Song]:
        # Walk the pool in similarity order, keeping the first (closest) song
        # per artist so every dispatched rec is a different artist. Artist
        # identity is Album.artist_id; songs without one (null) collapse to a
        # single slot. Returns fewer than `limit` when the pool lacks enough
        # distinct artists.
        seen_artists = set()
        null_used = False
        results = []
        for song, artist_id in pool:
            if artist_id is None:
                if null_used:
                    continue
                null_used = True
            elif artist_id in seen_artists:
                continue
            else:
                seen_artists.add(artist_id)
            results.append(song)
            if len(results) == limit:
                break
        return results

    def query_recommendations(self, user: User, db: Session, limit: int = 10) -> tuple[Song, list[Song]]:
        # Over-fetch this many candidates by similarity, then dedupe down to
        # `limit` distinct artists. 5x leaves headroom when nearby candidates
        # cluster on a few artists while staying cheap against the HNSW index.
        pool_size = limit * 5

        # P5a: pgvector's HNSW post-filters within ef_search candidates, so the
        # default ef_search=40 under-returns when we ask for pool_size=50 (the
        # fallback kNN came back with only 39 rows, shrinking the dedupe pool).
        # Scope ef_search to 2x pool_size for this transaction so the pool fills.
        # Capped here intentionally — much higher flips the genre-filtered branch
        # to an index plan that post-filters down to a handful of rows.
        # set_config(..., is_local=true) is the parameterizable equivalent of
        # `SET LOCAL` (plain SET won't take a bound parameter).
        db.execute(
            text("SELECT set_config('hnsw.ef_search', :ef, true)"),
            {"ef": str(pool_size * 2)},
        )

        query_entry = (
            db.query(UserTopSong)
            .filter(
                UserTopSong.user_id == user.id,
                UserTopSong.song_id != None,
                UserTopSong.used_as_query == False,
            )
            .first()
        )
        if query_entry is None:
            # A6: every processed candidate has already been a query seed. Recycle
            # them — reset used_as_query so the pool can be walked again — instead of
            # re-fetching from Spotify and rebuilding the snapshot. The re-pick is
            # intentionally order-agnostic: already_recommended (below) dedupes prior
            # recs, so reusing a seed still yields a distinct dispatch.
            db.query(UserTopSong).filter(
                UserTopSong.user_id == user.id,
                UserTopSong.song_id != None,
            ).update({UserTopSong.used_as_query: False}, synchronize_session=False)
            query_entry = (
                db.query(UserTopSong)
                .filter(
                    UserTopSong.user_id == user.id,
                    UserTopSong.song_id != None,
                    UserTopSong.used_as_query == False,
                )
                .first()
            )
        query_song = query_entry.song
        query_genre = query_entry.genre
        query_entry.used_as_query = True

        already_recommended = (
            db.query(UserRecommendation.song_id)
            .filter(UserRecommendation.user_id == user.id)
            .subquery()
        )

        # Each row carries its album's artist_id so we can dedupe by artist.
        # outerjoin keeps album-less songs, whose null artist_id collapses to
        # a single slot in _dedupe_by_artist.
        base_query = (
            db.query(Song, Album.artist_id)
            .outerjoin(Song.album)
            .options(selectinload(Song.album))
            .filter(Song.is_candidate == True)
            .filter(Song.id != query_song.id)
            .filter(Song.id.not_in(already_recommended))
            .order_by(Song.embedding.cosine_distance(query_song.embedding))
        )

        # Filter candidates by album genre matching the query song's genre.
        # Candidate genre is derived from the album they belong to (Album.genre).
        results = []
        if query_genre:
            pool = (
                base_query
                .filter(Album.genre == query_genre)
                .limit(pool_size)
                .all()
            )
            results = self._dedupe_by_artist(pool, limit)

        if len(results) < limit:
            pool = base_query.limit(pool_size).all()
            results = self._dedupe_by_artist(pool, limit)

        dispatch_date = today_pst()
        for song in results:
            db.add(UserRecommendation(
                user_id=user.id,
                song_id=song.id,
                query_song_id=query_song.id,
                dispatch_date=dispatch_date,
            ))
        db.commit()

        return query_song, results

    def get_todays_dispatch(self, user: User, db: Session):
        rows = (
            db.query(UserRecommendation)
            .options(
                selectinload(UserRecommendation.song).selectinload(Song.album),
                selectinload(UserRecommendation.query_song),
            )
            .filter(
                UserRecommendation.user_id == user.id,
                UserRecommendation.dispatch_date == today_pst(),
            )
            .order_by(UserRecommendation.id.asc())
            .all()
        )
        if not rows:
            return None
        return rows[0].query_song, [r.song for r in rows]


def get_ingest_service(request: Request) -> SpotifyIngestService:
    return request.app.state.ingest_service
