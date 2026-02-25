import os
from pathlib import Path
from dotenv import load_dotenv
import re

from data_pipeline.tools.database_manager import DatabaseManager
from data_pipeline.tools.datamodels import EmbeddingWithMetadata
from data_pipeline.song_pipeline.pipeline_stage import PipelineStage
from queue import Queue

# Load environment variables from .env-postgres in project root
env_path = Path(__file__).resolve().parents[2] / ".env-postgres"
load_dotenv(dotenv_path=env_path)

DB_NAME = os.getenv("POSTGRES_DB")
USER = os.getenv("POSTGRES_USER")
PASSWORD = os.getenv("POSTGRES_PASSWORD")
HOST = os.getenv("POSTGRES_HOST", "localhost")
PORT = os.getenv("POSTGRES_PORT", "5432")

class SongDBWriter(PipelineStage):
    def __init__(self, embed_queue: Queue, batch_size: int):
        super().__init__(name="SongDBWriter")
        self.db_manager = DatabaseManager(
            db_name=DB_NAME,
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT
        )
        self.db_manager.connect()
        self.embed_queue = embed_queue
        self.batch_size = batch_size

    def run(self):
        buffer = []

        while True:
            item = self.embed_queue.get()

            if item is None:
                break

            print(f'Adding {item.metadata.title} to DB buffer.')
            buffer.append(item)

            if len(buffer) >= self.batch_size:
                try:
                    self._flush(buffer)
                    print(f'{self.batch_size} songs fully processed')
                except Exception as e:
                    print(f'[SongDBWriter] Error flushing batch: {e}')
                    raise
                buffer.clear()

        if buffer:
            try:
                self._flush(buffer)
            except Exception as e:
                print(f'[SongDBWriter] Error flushing final batch: {e}')
                raise

    def _flush(self, buffer: list[EmbeddingWithMetadata]) -> None:
        """Insert songs with metadata into database"""
        # Prepare data for batch insert
        rows = []
        album_ids = set()
        paths_for_delete = set()
        for item in buffer:
            paths_for_delete.add(item.file_path)
            song_title = self._extract_name(str(item.file_path.stem))
            album_ids.add(item.metadata.album_id)

            rows.append((
                item.metadata.album_id,  # Foreign key to albums table
                song_title,
                item.metadata.artist_name,
                item.metadata.title,  # album name
                item.embedding.tolist()  # Convert numpy array to list for PostgreSQL
            ))

        # Batch insert
        self.db_manager.insert_rows(
            "songs",
            ["album_id", "title", "artist_name", "album_title", "embedding"],
            rows
        )
        # Mark all processed albums as completed
        self.db_manager.update_rows_by_ids("albums", "work_status", "completed", list(album_ids))
        self._delete_processed_songs(paths_for_delete)
        buffer.clear()
        
        
    def _extract_name(self, song_title:str) -> str:
        parts = re.split(r"\d+\s-?\s", song_title)
        song_title = parts[1] if len(parts) > 1 else parts[0]
        song_title = song_title.replace("-", " ")
        song_title = song_title.capitalize()
        return song_title
        
    def _delete_processed_songs(self, paths:set[Path]) -> None:
        for path in paths:
            print(f'Deleting {path.stem}')
            os.remove(path)
        
