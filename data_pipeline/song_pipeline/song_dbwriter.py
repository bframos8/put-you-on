import os
import re
from pathlib import Path
from queue import Queue

from data_pipeline.db.manager import DatabaseManager
from data_pipeline.models.datamodels import EmbeddingWithMetadata
from data_pipeline.song_pipeline.stage import PipelineStage
from data_pipeline.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

class SongDBWriter(PipelineStage):
    def __init__(self, embed_queue: Queue, batch_size: int):
        super().__init__(name="SongDBWriter")
        self.db_manager = DatabaseManager(
            db_name=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
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

        # Batch insert, skipping any songs already in the db for this album
        self.db_manager.insert_rows_ignore_conflicts(
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
        
