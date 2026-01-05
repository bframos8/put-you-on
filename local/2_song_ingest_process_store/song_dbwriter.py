from tools.database_manager import DatabaseManager
from tools.datamodels import EmbeddingWithMetadata
from pipeline_stage import PipelineStage
from queue import Queue

class SongDBWriter(PipelineStage):
    def __init__(self, embed_queue: Queue, batch_size: int):
        super().__init__(name="SongDBWriter")
        self.db_manager = DatabaseManager(
            db_name="put_you_on_db",
            user="ramos",
            password="",
            host="localhost",
            port="5432"
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

            buffer.append(item)

            if len(buffer) >= self.batch_size:
                self._flush(buffer)
                buffer.clear()

        if buffer:
            self._flush(buffer)

    def _flush(self, buffer: list[EmbeddingWithMetadata]) -> None:
        """Insert songs with metadata into database"""
        # Prepare data for batch insert
        values = []
        for item in buffer:
            # Extract song filename as title (you may want to parse this differently)
            song_title = item.file_path.stem

            values.append((
                item.metadata.album_id,  # Foreign key to albums table
                song_title,
                item.metadata.artist_name,
                item.metadata.title,  # album name
                item.embedding.tolist()  # Convert numpy array to list for PostgreSQL
            ))

        # Batch insert
        self.db_manager.execute_query(
            "INSERT INTO songs (album_id, title, artist_name, album_name, embedding) VALUES %s",
            values
        )