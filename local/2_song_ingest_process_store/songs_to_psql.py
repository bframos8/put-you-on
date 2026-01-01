from song_embedder import SongEmbedder
from song_downloader import SongDownloader
from song_dbwriter import SongDBWriter
from local.tools.database_manager import DatabaseManager
from queue import Queue

if __name__ == "__main__":
   
    audio_queue = Queue(maxsize=32)
    embed_queue = Queue(maxsize=64)
    
    downloader = SongDownloader(audio_queue)
    embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16)
    db_writer = SongDBWriter(embed_queue, batch_size=100)
    
    downloader.start()
    embedder.start()
    db_writer.start()
    
    downloader.join()
    audio_queue.put(None)  # Signal embedder to stop
    embedder.join()
    embed_queue.put(None)  # Signal db_writer to stop
    db_writer.join()