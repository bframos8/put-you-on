import os
import shutil
import threading
from pathlib import Path
from queue import Queue

from data_pipeline.song_pipeline.song_embedder import SongEmbedder
from data_pipeline.song_pipeline.song_downloader import SongDownloader
from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter

if __name__ == "__main__":
    # Just in case removal of previously downloaded songs.
    shutil.rmtree(Path(__file__).parent / "downloads", ignore_errors=True)

    stop_event = threading.Event()

    cores = os.cpu_count() or 4
    audio_queue = Queue(maxsize=cores * 2)   # ~20 slots on M4
    embed_queue = Queue(maxsize=cores)        # batches, fewer slots needed

    downloader = SongDownloader(audio_queue, stop_event, batch_limit=50)
    embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16, stop_event=stop_event)
    db_writer = SongDBWriter(embed_queue, stop_event)

    downloader.start()
    embedder.start()
    db_writer.start()

    downloader.join()
    embedder.join()
    db_writer.join()

    shutil.rmtree(Path(__file__).parent / "downloads", ignore_errors=True)

    for stage in (downloader, embedder, db_writer):
        if stage.error:
            raise RuntimeError(f"Pipeline failed in {stage.name}") from stage.error
