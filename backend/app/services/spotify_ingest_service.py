import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import Request
from sqlalchemy import and_, exists, func, or_, text

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
        # Walk the pool in the order the query returned it, keeping the first song
        # per artist so every dispatched rec is a different artist. Artist
        # identity is Album.artist_id; songs without one (null) collapse to a
        # single slot. Returns fewer than `limit` when the pool lacks enough
        # distinct artists.
        #
        # "In similarity order" only approximately, for the genre branch: it runs
        # with hnsw.iterative_scan='relaxed_order', which returns rows slightly out
        # of distance order in exchange for actually filling the pool. So the song
        # kept for an artist may not be that artist's very closest. For a daily
        # feed of ten recs that is not worth a re-sort, and it beats the alternative
        # of a pool that comes back half empty.
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

        # HNSW tuning is set per branch below rather than once here, because the two
        # branches want opposite things from ef_search. See each branch for why.
        # set_config(..., is_local=true) is the parameterizable equivalent of
        # `SET LOCAL` (plain SET won't take a bound parameter).

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

        # Exclude anything this user has already been given. NOT EXISTS rather than
        # `Song.id.not_in(subquery)`, and the difference is not stylistic: `NOT IN`
        # against a subquery cannot become an anti-join, because SQL's NULL semantics
        # mean one NULL in the subquery would make the whole predicate unknown. So
        # Postgres compiles it to a hashed SubPlan, and the distorted row estimate
        # that comes with it was enough to push the planner off the HNSW index and
        # onto a sequential scan for every large genre. NOT EXISTS is a true
        # anti-join, and the planner then picks the index on merit.
        #
        # Measured on prod, warm, per genre (2026-09-25):
        #   latin   NOT IN -> seq 81 ms / 71,715 buffers | NOT EXISTS -> HNSW 9.0 ms / 3,142
        #   blues   NOT IN -> seq 85 ms / 67,889 buffers | NOT EXISTS -> HNSW 9.9 ms / 3,613
        #   reggae  NOT IN -> seq 75 ms / 63,742 buffers | NOT EXISTS -> HNSW 6.2 ms / 1,346
        # The buffer column is the one that matters: the instance cannot cache the
        # table, so buffer traffic is what turns into disk reads in production.
        already_recommended = ~exists().where(
            and_(
                UserRecommendation.user_id == user.id,
                UserRecommendation.song_id == Song.id,
            )
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
            .filter(already_recommended)
            .order_by(Song.embedding.cosine_distance(query_song.embedding))
        )

        # Filter candidates by genre, reading Song.genre rather than Album.genre
        # (P5b). The two are equivalent for candidates — the songs_fill_genre
        # trigger denormalizes albums.genre onto songs on insert, albums.genre is
        # never updated afterwards, and all 110,833 candidates have one — but they
        # are very different to the planner. A predicate on Album.genre sits on the
        # inner side of the LEFT JOIN, which lets Postgres simplify the join to an
        # INNER JOIN and drive from albums, hash-joining songs: that reads the whole
        # table and throws away the index ordering. On Song.genre it is a qual on
        # songs itself, so the HNSW index can drive the scan.
        #
        # iterative_scan is the other half, and the two only work together. pgvector
        # does not push the genre predicate into graph traversal; it post-filters
        # within the index scan, so a plain scan returns a fraction of pool_size.
        # 'relaxed_order' lets it resume from discarded candidates until the pool
        # fills, at the cost of approximate ordering (see _dedupe_by_artist).
        #
        # ef_search goes DOWN to 40 here, which reverses P5a. P5a raised it to
        # 2x pool_size because the pool under-filled; iterative scan now does that
        # job properly, and the high value had become actively harmful: pgvector's
        # cost estimate scales with ef_search, so at 100 the index path costed 6978
        # against a sequential scan's 6052 and the planner rejected its own index.
        # At 40 it costs 4262 and wins on merit, no planner hints needed.
        # Measured on prod, 110,833 candidates (2026-09-25):
        #   ef=100  -> Parallel Seq Scan, 86.7 ms, 79,403 buffers
        #   ef=40   -> HNSW Index Scan,    2.8 ms,  1,778 buffers
        # Both returned the full 50. The seq scan only looked competitive because
        # everything was cached on a temporarily-scaled-up instance; the buffer
        # count is the number that predicts behaviour on the real one.
        results = []
        if query_genre:
            db.execute(
                text("SELECT set_config('hnsw.ef_search', '40', true)")
            )
            db.execute(
                text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
            )
            pool = (
                base_query
                .filter(Song.genre == query_genre)
                .limit(pool_size)
                .all()
            )
            results = self._dedupe_by_artist(pool, limit)

        if len(results) < limit:
            # The unfiltered fallback wants the opposite settings. Nothing post-filters
            # it, so it needs no iterative scan and gets exact distance order free —
            # but HNSW returns at most ef_search candidates, so ef must exceed
            # pool_size or the pool is capped at 40 (P5a's original finding: 39 rows
            # back for a 50-row request). 2x leaves margin.
            db.execute(
                text("SELECT set_config('hnsw.ef_search', :ef, true)"),
                {"ef": str(pool_size * 2)},
            )
            db.execute(
                text("SELECT set_config('hnsw.iterative_scan', 'off', true)")
            )
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
