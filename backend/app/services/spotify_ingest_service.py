import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from fastapi import Request
from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

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

# How many times a seed's audio fetch may fail before we give up on it (10.5). Downloads
# fail for two different reasons and this number has to serve both: a transient network
# or provider hiccup, which a retry fixes, and a track that simply cannot be fetched —
# unavailable, region-locked, or blocked at the source — which no number of retries fixes.
# Three is enough to ride out the former without spending minutes per request on the
# latter. Reaching it sets ingest_failed_at, which is what makes the seed terminal and
# stops snapshot_is_stale from re-queueing the whole ingest forever.
INGEST_MAX_ATTEMPTS = 3

# How long a worker's claim on a seed is good for (10.6). A claim is a lease, not a lock:
# the worker holds no database connection while it downloads, so the only thing stopping a
# crashed worker from parking a row forever is this expiry. It has to comfortably exceed
# the time to download and embed a whole batch — measured at well under a minute per track
# on a residential connection — while staying short enough that a dead worker's rows come
# back on their own. Fifteen minutes covers a batch of three with an order of magnitude to
# spare. The cost of it being too long is only a longer spinner; the cost of it being too
# short is two workers downloading the same track.
INGEST_CLAIM_LEASE_SECONDS = 900


def _redact_secrets(text: str) -> str:
    """Strip known secret values out of a string before it is stored or logged.

    Belt and braces behind _download's own handling. The error text that reaches
    ingest_error comes from a subprocess and, once the worker (10.6) is running, from
    another machine entirely — so the value is worth checking at the point of storage
    rather than trusting every producer of it to be careful forever.

    Matching on the exact configured value, not a pattern: no false positives, nothing to
    tune, and it fails safe if the variable is unset (nothing to match, nothing redacted).
    """
    for name in ("SPOTIFY_CLIENT_SECRET", "SPOTIFY_CLIENT_ID", "INGEST_WORKER_TOKEN"):
        value = os.getenv(name)
        if value and value in text:
            text = text.replace(value, f"[redacted:{name}]")
    return text


class NoUsableSeedsError(RuntimeError):
    """Every one of the user's seeds failed or is still unprocessed, so there is nothing
    to build a recommendation from. A typed error rather than an AttributeError deep in
    the query, so callers can turn it into an honest response instead of a 500 (10.5)."""


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
            # NOT check=True, and this is a security fix rather than a style choice.
            # CalledProcessError stringifies the entire argv, which carries
            # --client-secret. That string reaches _record_failure, which stores its
            # first 500 characters in user_top_songs.ingest_error — and the secret sits
            # well inside that window. So every failed download was writing the Spotify
            # client secret into the database and the container logs.
            result = subprocess.run(
                ["spotdl", "--no-cache", "--format", "mp3", "--bitrate", "320k",
                "--client-id", os.getenv("SPOTIFY_CLIENT_ID"),
                "--client-secret", os.getenv("SPOTIFY_CLIENT_SECRET"),
                "--output", str(job_dir),
                spotify_url],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Keep the lines that carry words: spotdl prints rich-formatted
                # tracebacks, so most of the output is box drawing and source echo, and
                # this string is what a human reads when triaging a failed seed.
                tail = [
                    line.strip(" │╭╮╰╯─")
                    for line in (result.stderr or result.stdout or "").splitlines()
                    if line.strip(" │╭╮╰╯─")
                ]
                raise RuntimeError(
                    f"spotdl exited {result.returncode}: "
                    + (" | ".join(tail[-2:]) if tail else "no output")
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
        # Refresh the seed set, KEEPING per-track state for tracks that are still in it.
        #
        # This used to be an unconditional delete-then-insert. That quietly defeated the
        # whole attempt cap (10.5): a failed seed would be wiped and re-added with
        # ingest_attempts back at 0 on every pass, so it could never reach
        # INGEST_MAX_ATTEMPTS and never become terminal — the loop this was meant to end.
        # It also discarded used_as_query, losing A6's place in the recycling walk.
        #
        # Someone's top tracks barely move between snapshots, so nearly every row is a
        # survivor. Only genuinely departed tracks are deleted.
        snapshot_at = datetime.now()
        track_ids = [track["id"] for track in tracks]

        existing_rows = {
            row.spotify_track_id: row
            for row in db.query(UserTopSong).filter(UserTopSong.user_id == user.id).all()
        }
        for track_id, row in existing_rows.items():
            if track_id not in track_ids:
                db.delete(row)

        existing_by_track = {
            s.spotify_track_id: s
            for s in db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
        } if track_ids else {}

        for track in tracks:
            spotify_track_id = track["id"]
            song = existing_by_track.get(spotify_track_id)
            row = existing_rows.get(spotify_track_id)
            if row is None:
                row = UserTopSong(user_id=user.id, spotify_track_id=spotify_track_id)
                db.add(row)
            # Metadata is refreshed from Spotify every time; queue state
            # (ingest_attempts, ingest_failed_at, ingest_error, used_as_query) is
            # deliberately left alone on survivors.
            row.spotify_url = track["external_urls"]["spotify"]
            row.image_url = track["album"]["images"][0]["url"]
            row.artist_name = track["artists"][0]["name"]
            row.track_title = track["name"]
            row.album_title = track["album"]["name"]
            row.duration_ms = track.get("duration_ms")
            row.snapshot_at = snapshot_at
            # Only fill these from the corpus; never blank out a link we already have.
            if song is not None:
                row.song_id = song.id
                row.genre = song.genre
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
                    self._record_failure(top_song, e, db)
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
                    # After the rollback, deliberately: recording the attempt inside the
                    # failed transaction would roll the counter back with it, and the
                    # seed would never reach the cap.
                    self._record_failure(top_song, e, db)
                finally:
                    self._cleanup(audio_path)

            if success and not first_done and on_first_success:
                first_done = self._fire_first_success(on_first_success, db)

    @staticmethod
    def _record_failure(top_song: UserTopSong, error: Exception, db: Session) -> None:
        # Count the attempt, and retire the seed once it hits the cap. ingest_failed_at
        # being set is what makes snapshot_is_stale stop treating this row as outstanding
        # work, which is what ends the re-queue loop (10.5).
        top_song.ingest_attempts = (top_song.ingest_attempts or 0) + 1
        # Truncated: this is shown to the user and a spotdl traceback can run to
        # kilobytes. The full text is in the container logs.
        top_song.ingest_error = _redact_secrets(str(error))[:500]
        # Release the worker's lease (10.6). A failed seed that still has attempts left
        # should be immediately re-claimable rather than sitting out the rest of its
        # lease; in the in-process path this is simply always None already.
        top_song.claimed_at = None
        if top_song.ingest_attempts >= INGEST_MAX_ATTEMPTS:
            top_song.ingest_failed_at = datetime.now()
            # ERROR, not WARNING (10.9): this is the one event in the whole ingest path
            # that fires exactly once per seed, at the transition, and it means a user has
            # permanently lost a seed. sentry-sdk's default LoggingIntegration promotes
            # ERROR to an issue, so this is what makes a degraded ingest visible without
            # anyone reading logs.
            #
            # %s parameters, never an f-string: Sentry groups on the raw message, so
            # interpolating the ids into it would fragment one issue into one per seed.
            logger.error(
                "Giving up on seed %s (user %s, %s) after %d attempts: %s",
                top_song.id, top_song.user_id, top_song.track_title,
                top_song.ingest_attempts, top_song.ingest_error,
            )
        db.commit()

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
        # "Stale" means the snapshot needs a (re)build — it's empty, or there is still
        # unprocessed work worth doing. Pool exhaustion (all rows used as query seeds) is
        # deliberately NOT stale: query_recommendations recycles the existing candidates
        # instead of re-fetching from Spotify (A6).
        #
        # A seed that has exhausted INGEST_MAX_ATTEMPTS does NOT count as outstanding
        # work (10.5). Before this, an unfetchable track kept the snapshot stale forever,
        # so every request re-fetched top tracks from Spotify, rewrote the seed set and
        # re-ran the whole failing ingest — an infinite loop that cost a Spotify API call
        # and ten downloads per iteration and never surfaced anywhere, because the
        # failures are warnings rather than exceptions.
        total = db.query(func.count()).select_from(UserTopSong).filter(
            UserTopSong.user_id == user.id
        ).scalar()
        if total == 0:
            return True

        return SpotifyIngestService.pending_seed_count(user, db) > 0

    @staticmethod
    def pending_seed_count(user: User, db: Session) -> int:
        # Seeds still worth working on: no song behind them yet, and not yet retired at
        # INGEST_MAX_ATTEMPTS. This is the second half of snapshot_is_stale, pulled out
        # because get_recs needs the same number on its own in worker mode (10.6) to
        # decide whether anything is already queued.
        #
        # A row whose song_id is set but whose genre is NULL is deliberately NOT pending,
        # matching what snapshot_is_stale has always counted: query_recommendations
        # handles a null genre by falling back to the unfiltered branch, so there is
        # nothing outstanding to do for it.
        #
        # A claimed row still counts. A worker holding a lease is work in progress, and
        # treating it as finished would let get_recs re-fetch the snapshot underneath it.
        return db.query(func.count()).select_from(UserTopSong).filter(
            UserTopSong.user_id == user.id,
            UserTopSong.song_id == None,
            UserTopSong.ingest_failed_at == None,
        ).scalar()

    @staticmethod
    def usable_seed_count(user: User, db: Session) -> int:
        # Seeds that actually have an embedded Song behind them, i.e. what
        # query_recommendations can pick a query song from. Zero means it must not be
        # called at all: it would reach `query_entry.song` on None and raise (10.5).
        return db.query(func.count()).select_from(UserTopSong).filter(
            UserTopSong.user_id == user.id,
            UserTopSong.song_id != None,
        ).scalar()

    @staticmethod
    def failed_seed_count(user: User, db: Session) -> int:
        # Seeds retired after INGEST_MAX_ATTEMPTS, so the user can be told how many of
        # their tracks couldn't be processed rather than silently getting a thinner pool.
        return db.query(func.count()).select_from(UserTopSong).filter(
            UserTopSong.user_id == user.id,
            UserTopSong.ingest_failed_at != None,
        ).scalar()

    @staticmethod
    def claim_pending_seeds(db: Session, limit: int, lease_seconds: int) -> list[dict]:
        """Lease up to `limit` pending seeds to a worker, across all users (10.6).

        The standard Postgres work-queue statement: the inner SELECT takes row locks and
        SKIP LOCKED steps over anything another claim is already holding, so two workers
        polling at the same moment get disjoint sets instead of one of them blocking.
        The outer UPDATE only re-locks rows this transaction already holds, so it cannot
        re-block on what the inner select skipped.

        Three things here are load-bearing and easy to get wrong:

        - **It commits.** `get_db` closes the session without committing, which rolls
          back, so without this the lease would be discarded the moment the request ends
          and every poll would hand out the same rows again — the worker would download
          each track over and over and SKIP LOCKED would buy nothing.
        - **`synchronize_session=False`.** With an `IN (subquery)` criteria the ORM
          cannot use its `evaluate` strategy and falls back to `fetch`, which rewrites
          the statement to add its own supplemental RETURNING columns on top of ours.
        - **RETURNING names columns, not the entity**, so what comes back is a plain row
          rather than an ORM object built out of an UPDATE.

        The lease bound is computed in SQL (`now() - interval`), never against a Python
        clock: the only machine that matters is the database's, and the worker's is in
        another timezone entirely.
        """
        claimable = (
            select(UserTopSong.id)
            .where(
                UserTopSong.song_id == None,
                UserTopSong.ingest_failed_at == None,
                or_(
                    UserTopSong.claimed_at == None,
                    UserTopSong.claimed_at < func.now() - timedelta(seconds=lease_seconds),
                ),
            )
            .order_by(UserTopSong.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = db.execute(
            update(UserTopSong)
            .where(UserTopSong.id.in_(claimable))
            .values(claimed_at=func.now())
            .returning(
                UserTopSong.id,
                UserTopSong.spotify_url,
                UserTopSong.track_title,
                UserTopSong.artist_name,
                UserTopSong.ingest_attempts,
            )
            .execution_options(synchronize_session=False)
        ).all()
        db.commit()

        # Logged because a worker that stops claiming is otherwise completely invisible:
        # the symptom is users stuck on "Building your drop", and nothing reaches Sentry
        # (the same blind spot that hid the 10.3 loop for three months).
        if rows:
            logger.info("Claimed %d seed(s) for the ingest worker", len(rows))
        return [
            {
                "id": row.id,
                "spotify_url": row.spotify_url,
                "track_title": row.track_title,
                "artist_name": row.artist_name,
                "attempts": row.ingest_attempts,
            }
            for row in rows
        ]

    @staticmethod
    def complete_seed(
        top_song_id: int, genre: str | None, embedding: list[float], db: Session
    ) -> str:
        """Store a worker's finished ingest against one seed (10.6).

        Mirrors the write half of `process_top_tracks`: reuse the Song for this Spotify
        track if one already exists, otherwise create it as a non-candidate, then link
        the seed to it. Returns a short status the endpoint turns into a response.

        Idempotent on purpose. A deploy recreates the backend container mid-request
        (8.3), so the worker can perfectly reasonably POST a result that already landed;
        that has to be a no-op rather than a second Song or an overwrite of a newer one.
        """
        top_song = db.query(UserTopSong).filter(UserTopSong.id == top_song_id).first()
        if top_song is None:
            return "unknown"

        if top_song.song_id is not None:
            # Already done — by an earlier POST of this same result, or by another user's
            # ingest of the same track. Release the lease and say so; do not overwrite,
            # because a worker whose lease expired could otherwise clobber a newer
            # embedding with a stale one.
            top_song.claimed_at = None
            db.commit()
            return "already_done"

        existing = (
            db.query(Song)
            .filter(Song.spotify_track_id == top_song.spotify_track_id)
            .first()
        )
        if existing is not None:
            song = existing
            # Same as the in-process path: the freshly classified genre wins. These rows
            # are only ever other users' seeds (corpus songs have no spotify_track_id),
            # so this is not overwriting anything the Bandcamp pipeline produced.
            song.genre = genre
        else:
            song = Song(
                title=top_song.track_title,
                artist_name=top_song.artist_name,
                album_title=top_song.album_title,
                spotify_track_id=top_song.spotify_track_id,
                genre=genre,
                embedding=embedding,
                is_candidate=False,
            )
            try:
                # SAVEPOINT, not a bare flush. spotify_track_id is unique and two workers
                # can be finishing the same popular track for two different users at the
                # same moment; a failed flush aborts the whole transaction, so without
                # the savepoint the recovery query below would itself raise
                # InFailedSqlTransaction.
                with db.begin_nested():
                    db.add(song)
                    db.flush()
            except IntegrityError:
                song = (
                    db.query(Song)
                    .filter(Song.spotify_track_id == top_song.spotify_track_id)
                    .one()
                )

        top_song.song_id = song.id
        top_song.genre = genre
        top_song.claimed_at = None
        top_song.ingest_error = None
        db.commit()
        return "ok"

    @staticmethod
    def record_seed_failure(
        top_song_id: int, error: str, db: Session
    ) -> tuple[int, bool] | None:
        """Record a worker's failed ingest (10.6). Returns (attempts, terminal), or None
        if the seed no longer exists — the user's top tracks may have moved on while the
        worker was downloading, in which case add_user_top_songs deleted the row.

        Thin on purpose: the counting, truncation and retirement rules live in
        _record_failure, so the worker path and the in-process path cannot diverge on
        what counts as a failure.
        """
        top_song = db.query(UserTopSong).filter(UserTopSong.id == top_song_id).first()
        if top_song is None:
            return None
        SpotifyIngestService._record_failure(top_song, RuntimeError(error), db)
        return top_song.ingest_attempts, top_song.ingest_failed_at is not None

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
        if query_entry is None:
            # No seed has a Song behind it — every one either failed or was never
            # processed. Before 10.5 this was unreachable, because an unprocessed
            # snapshot always counted as stale and got re-ingested instead. Now that a
            # failed seed is terminal, it IS reachable, and without this guard the next
            # line raises AttributeError on None and the endpoint 500s — which the
            # frontend swallows silently, leaving a blank page and no explanation.
            # Callers check usable_seed_count() first; this is the backstop.
            raise NoUsableSeedsError(
                f"user {user.id} has no seed with a processed song to query from"
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
