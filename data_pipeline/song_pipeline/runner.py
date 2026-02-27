from data_pipeline.song_pipeline.song_embedder import SongEmbedder
from data_pipeline.song_pipeline.song_downloader import SongDownloader
from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
from queue import Queue
import shutil
from pathlib import Path

if __name__ == "__main__":
   #Just in case removal of previously downloaded songs.
    shutil.rmtree(Path(__file__).parent / "downloads", ignore_errors=True)

    audio_queue = Queue(maxsize=16)
    embed_queue = Queue(maxsize=32)

    downloader = SongDownloader(audio_queue)
    embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16)
    db_writer = SongDBWriter(embed_queue, batch_size=16)

    downloader.start()
    embedder.start()
    db_writer.start()


    downloader.join()
    embedder.join()
    db_writer.join()

    shutil.rmtree(Path(__file__).parent / "downloads", ignore_errors=True)
