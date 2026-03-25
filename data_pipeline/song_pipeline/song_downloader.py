import subprocess
from pathlib import Path

from data_pipeline.models.datamodels import AlbumMetadata, AudioWithMetadata
from data_pipeline.song_pipeline.stage import PipelineStage
from data_pipeline.db.manager import DatabaseManager
from data_pipeline.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

DOWNLOADS_DIR = Path(__file__).parent / "downloads"

class SongDownloader(PipelineStage):
    def __init__(self, output_queue):
        super().__init__(name="SongDownloader")
        self.db_manager = DatabaseManager(
            db_name=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        self.db_manager.connect()
        self.output_queue = output_queue

    def run(self):
        albums_to_download = self._get_albums_to_download()

        for album_data in albums_to_download:
            # Create metadata object
            metadata = AlbumMetadata(
                album_id=album_data[0],
                title=album_data[1],
                artist_name=album_data[2],
                url=album_data[3]
            )

            # Download songs and get file paths
            audio_file_paths = self._download_songs(metadata.album_id, metadata.url)

            # Put each audio file path with metadata into queue
            for audio_file_path in audio_file_paths:
                audio_with_metadata = AudioWithMetadata(
                    file_path=audio_file_path,
                    metadata=metadata
                )
                print(f'Downloaded {audio_with_metadata.metadata.title} at {audio_with_metadata.file_path}')
                self.output_queue.put(audio_with_metadata)

        # Signal end of processing
        self.output_queue.put(None)

    def _get_albums_to_download(self):
        query = """
            UPDATE albums SET work_status = 'in_progress'
            WHERE work_status = 'pending'
            RETURNING id, title, artist_name, url;
        """
        results = self.db_manager.execute_query(query)
        return [row for row in results]

    def _download_songs(self, album_id: int, url: str) -> list[Path]:
        album_dir = DOWNLOADS_DIR / str(album_id)
        album_dir.mkdir(parents=True, exist_ok=True)

        subprocess.run([
            "bandcamp-dl",
            "-n",
            "--no-confirm",
            "--base-dir",
            str(album_dir),
            url,
        ])

        # Get all audio file paths (common formats)
        audio_extensions = {'.mp3', '.flac', '.wav', '.m4a', '.ogg'}
        audio_file_paths = [
            f for f in album_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in audio_extensions
        ]

        return audio_file_paths