import os
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import func, case

import essentia
import numpy as np
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs
from sqlalchemy.orm import Session

from ..db.models import Album, Song, User, UserRecommendation, UserTopSong

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

    def ingest(self, spotify_url: str, db: Session) -> Song:
        audio_path = self._download(spotify_url)
        try:
            embedding = self._embed(audio_path)
            song = self._write_to_db(audio_path, embedding, db)
        finally:
            self._cleanup(audio_path)
        return song

    def _download(self, spotify_url: str) -> Path:
        before = set(DOWNLOADS_DIR.rglob("*"))
        subprocess.run(
            ["spotdl", "--no-cache", "--format", "mp3", "--bitrate", "320k",
            "--client-id", os.getenv("SPOTIFY_CLIENT_ID"),
            "--client-secret", os.getenv("SPOTIFY_CLIENT_SECRET"),
            "--output", str(DOWNLOADS_DIR),
            spotify_url],
            check=True,
        )
        new_files = [
            f for f in DOWNLOADS_DIR.rglob("*")
            if f not in before and f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
        if not new_files:
            raise FileNotFoundError(f"spotdl produced no audio file for {spotify_url}")
        return new_files[0]

    def _embed(self, audio_path: Path) -> np.ndarray:
        audio = MonoLoader(
            filename=str(audio_path), sampleRate=16000, resampleQuality=4
        )()
        frame_embeddings = self.model(audio)
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
        if audio_path.exists():
            os.remove(audio_path)

    def add_user_top_songs(
        self,
        tracks: list[dict],
        user: User,
        db: Session,
        genre_map: dict[str, str | None] | None = None,
    ) -> None:
        db.query(UserTopSong).filter(UserTopSong.user_id == user.id).delete()
        snapshot_at = datetime.now()
        for track in tracks:
            spotify_track_id = track["id"]
            song = db.query(Song).filter(Song.spotify_track_id == spotify_track_id).first()
            db.add(UserTopSong(
                user_id=user.id,
                song_id=song.id if song else None,
                spotify_track_id=spotify_track_id,
                spotify_url=track["external_urls"]["spotify"],
                image_url=track["album"]["images"][0]["url"],
                artist_name=track["artists"][0]["name"],
                track_title=track["name"],
                album_title=track["album"]["name"],
                genre=genre_map.get(spotify_track_id) if genre_map else None,
                snapshot_at=snapshot_at,
            ))
        db.commit()

    def process_top_tracks(self, user: User, db: Session) -> None:
        unprocessed = (
            db.query(UserTopSong)
            .filter(UserTopSong.user_id == user.id, UserTopSong.song_id == None)
            .all()
        )
        for top_song in unprocessed:
            existing = db.query(Song).filter(Song.spotify_track_id == top_song.spotify_track_id).first()
            if existing:
                top_song.song_id = existing.id
                db.commit()
                continue

            print(f"Processing: {top_song.track_title} | {top_song.spotify_url}")
            try:
                audio_path = self._download(top_song.spotify_url)
            except Exception as e:
                print(f"Skipping {top_song.track_title}: download failed — {e}")
                continue

            print(f"Downloaded to: {audio_path}")
            try:
                embedding = self._embed(audio_path)
                song = Song(
                    title=top_song.track_title,
                    artist_name=top_song.artist_name,
                    album_title=top_song.album_title,
                    spotify_track_id=top_song.spotify_track_id,
                    genre=top_song.genre,
                    embedding=embedding.tolist(),
                    is_candidate=False,
                )
                db.add(song)
                db.flush()
                top_song.song_id = song.id
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Skipping {top_song.track_title}: processing failed — {e}")
            finally:
                self._cleanup(audio_path)

    def snapshot_is_stale(self, user: User, db: Session) -> bool:
        result = db.query(
            func.count().label("total"),
            func.count(UserTopSong.song_id).label("processed"),
            func.sum(case((UserTopSong.used_as_query == True, 1), else_=0)).label("queried"),
        ).filter(UserTopSong.user_id == user.id).one()

        if result.total == 0:
            return True
        has_unprocessed = result.processed < result.total
        all_queried = result.queried == result.total
        return has_unprocessed or all_queried

    def query_recommendations(self, user: User, db: Session, limit: int = 10) -> list[Song]:
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
        spotify_genre = query_entry.genre  # genre sourced from Spotify via UserTopSong
        query_entry.used_as_query = True

        already_recommended = (
            db.query(UserRecommendation.song_id)
            .filter(UserRecommendation.user_id == user.id)
            .subquery()
        )

        base_query = (
            db.query(Song)
            .filter(Song.is_candidate == True)
            .filter(Song.id != query_song.id)
            .filter(Song.id.not_in(already_recommended))
            .order_by(Song.embedding.cosine_distance(query_song.embedding))
        )

        # Filter candidates by album genre matching the Spotify song's genre.
        # Candidate genre is derived from the album they belong to (Album.genre).
        results = []
        if spotify_genre:
            results = (
                base_query
                .join(Song.album)
                .filter(Album.genre == spotify_genre)
                .limit(limit)
                .all()
            )

        if len(results) < limit:
            results = base_query.limit(limit).all()

        for song in results:
            db.add(UserRecommendation(user_id=user.id, song_id=song.id))
        db.commit()

        return query_song, results


def get_ingest_service(request: Request) -> SpotifyIngestService:
    return request.app.state.ingest_service
