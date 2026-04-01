from pathlib import Path
from threading import Event
import numpy as np
import essentia
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

essentia.log.warningActive = False
from data_pipeline.models.datamodels import AudioWithMetadata, EmbeddingWithMetadata
from data_pipeline.song_pipeline.stage import PipelineStage

GRAPH_FILE_PATH = str(Path(__file__).resolve().parents[1] / "models" / "discogs-effnet-bs64-1.pb")

def _check_metal() -> bool:
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            print(f"[SongEmbedder] Metal GPU active: {[g.name for g in gpus]}")
            return True
        print("[SongEmbedder] No Metal GPU found, using CPU")
    except Exception:
        print("[SongEmbedder] Could not query TF devices, using CPU")
    return False

class SongEmbedder(PipelineStage):
    def __init__(self, input_queue, output_queue, batch_size: int, stop_event: Event):
        super().__init__(name="SongEmbedder", stop_event=stop_event)
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.batch_size = batch_size
        _check_metal()
        self.model = TensorflowPredictEffnetDiscogs(graphFilename=GRAPH_FILE_PATH, output='PartitionedCall:1')

    def run(self):
        buffer = []
        try:
            while not self.stopped:
                item = self.input_queue.get()

                if item is None:
                    break

                audio_with_metadata: AudioWithMetadata = item

                audio = self._load_song(str(audio_with_metadata.file_path))
                embedding = self._embed_song(audio)

                embedding_with_metadata = EmbeddingWithMetadata(
                    file_path=audio_with_metadata.file_path,
                    embedding=embedding,
                    metadata=audio_with_metadata.metadata
                )

                print(f'Embedded {embedding_with_metadata.metadata.title}')
                buffer.append(embedding_with_metadata)

                if len(buffer) >= self.batch_size:
                    self._flush(buffer)
                    print("Flushed embed buffer")
                    buffer.clear()

        except Exception as e:
            self.error = e
            self.stop()
            print(f'[SongEmbedder] Fatal error: {e}')
        finally:
            if buffer:
                self._flush(buffer)
            self.output_queue.put(None)

    def _load_song(self, filepath: str):
        loader = MonoLoader(filename=filepath, sampleRate=16000, resampleQuality=4)
        return loader()

    def _embed_song(self, song):
        frame_embeddings = self.model(song)
        song_embedding = frame_embeddings.mean(axis=0)
        return song_embedding

    def _flush(self, buffer: list[EmbeddingWithMetadata]) -> None:
        """Flush buffer to output queue as a single batch"""
        self.output_queue.put(list(buffer))
