from data_pipeline.song_pipeline.song_embedder import SongEmbedder
from data_pipeline.song_pipeline.song_downloader import SongDownloader
from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
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
    embedder.join()
    db_writer.join()