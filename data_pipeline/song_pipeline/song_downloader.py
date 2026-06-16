import subprocess
import sys
import time
from pathlib import Path
from queue import Full
from threading import Event

from data_pipeline.models.datamodels import AlbumMetadata, AudioWithMetadata
from data_pipeline.song_pipeline.stage import PipelineStage
from data_pipeline.db.manager import DatabaseManager
from data_pipeline.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

DOWNLOADS_DIR = Path(__file__).parent / "downloads"
AUDIO_EXTENSIONS = {'.mp3', '.flac', '.wav', '.m4a', '.ogg'}

class SongDownloader(PipelineStage):
    def __init__(self, output_queue, stop_event: Event, batch_limit: int = 50):
        super().__init__(name="SongDownloader", stop_event=stop_event)
        self.db_manager = DatabaseManager(
            db_name=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        self.db_manager.connect()
        self.output_queue = output_queue
        self.batch_limit = batch_limit

    def run(self):
        try:
            while not self.stopped:
                albums_to_download = self._get_albums_to_download()
                if not albums_to_download:
                    break

                for album_data in albums_to_download:
                    if self.stopped:
                        break

                    metadata = AlbumMetadata(
                        album_id=album_data[0],
                        title=album_data[1],
                        artist_name=album_data[2],
                        url=album_data[3]
                    )

                    # Wait for headroom before downloading to avoid saturating the queue
                    while not self.stopped and self.output_queue.full():
                        time.sleep(0.2)

                    if self.stopped:
                        break

                    audio_file_paths = self._download_songs(metadata.album_id, metadata.url)

                    for audio_file_path in audio_file_paths:
                        if self.stopped:
                            break
                        audio_with_metadata = AudioWithMetadata(
                            file_path=audio_file_path,
                            metadata=metadata
                        )
                        print(f'Downloaded {audio_with_metadata.metadata.title} at {audio_with_metadata.file_path}')
                        self._put(audio_with_metadata)

        except Exception as e:
            self.error = e
            self.stop()
            print(f'[SongDownloader] Fatal error: {e}')
        finally:
            self.output_queue.put(None)

    def _put(self, item):
        """Put with stop-event awareness to avoid blocking indefinitely."""
        while not self.stopped:
            try:
                self.output_queue.put(item, timeout=0.5)
                return
            except Full:
                continue

    def _get_albums_to_download(self):
        query = f"""
            UPDATE albums SET work_status = 'in_progress'
            WHERE id IN (
                SELECT id FROM albums
                WHERE work_status = 'pending'
                LIMIT {self.batch_limit}
            )
            RETURNING id, title, artist_name, url;
        """
        results = self.db_manager.execute_query(query)
        return [row for row in results]

    def _download_songs(self, album_id: int, url: str) -> list[Path]:
        album_dir = DOWNLOADS_DIR / str(album_id)
        album_dir.mkdir(parents=True, exist_ok=True)

        bandcamp_dl = Path(sys.executable).parent / "bandcamp-dl"
        subprocess.run([
            str(bandcamp_dl),
            "-n",
            "--no-confirm",
            "--base-dir",
            str(album_dir),
            url,
        ])

        # Get all audio file paths (common formats)
        audio_file_paths = [
            f for f in album_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]

        return audio_file_paths
