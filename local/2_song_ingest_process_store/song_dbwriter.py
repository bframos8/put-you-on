from tools.database_manager import DatabaseManager
from queue import Queue

class SongDBWriter:
    def __init__(self, embed_queue: Queue, batch_size: int):
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
            
    def _flush(self, buffer: list) -> None:
        self.db_manager.execute_query(
            "INSERT INTO songs (id, title, artist_name, album_name, embedding) VALUES %s",
            buffer
        )