import os
import numpy as np
import essentia
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

essentia.log.warningActive = False
from data_pipeline.tools.datamodels import AudioWithMetadata, EmbeddingWithMetadata
from data_pipeline.song_pipeline.pipeline_stage import PipelineStage

GRAPH_FILE_PATH = os.path.join('data_pipeline', 'tools', 'discogs-effnet-bs64-1.pb')

class SongEmbedder(PipelineStage):
    def __init__(self, input_queue, output_queue, batch_size: int):
        super().__init__(name="SongEmbedder")
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.batch_size = batch_size
        self.model = TensorflowPredictEffnetDiscogs(graphFilename=GRAPH_FILE_PATH, output='PartitionedCall:1')

    def run(self):
        buffer = []

        while True:
            item = self.input_queue.get()

            # Check for termination signal
            if item is None:
                break

            # Process the audio file
            audio_with_metadata: AudioWithMetadata = item

            # Load and embed the song
            audio = self._load_song(str(audio_with_metadata.file_path))
            embedding = self._embed_song(audio)

            # Create embedding with metadata
            embedding_with_metadata = EmbeddingWithMetadata(
                file_path=audio_with_metadata.file_path,
                embedding=embedding,
                metadata=audio_with_metadata.metadata
            )

            # Add to buffer
            print(f'Embedded {embedding_with_metadata.metadata.title}')
            buffer.append(embedding_with_metadata)

            # Flush if batch size reached
            if len(buffer) >= self.batch_size:
                self._flush(buffer)
                print("Flushed embedd buffer")
                buffer.clear()

        # Flush remaining items
        if buffer:
            self._flush(buffer)

        # Signal next stage to stop
        self.output_queue.put(None)

    def _load_song(self, filepath: str):
        loader = MonoLoader(filename=filepath, sampleRate=16000, resampleQuality=4)
        return loader()

    def _embed_song(self, song):
        frame_embeddings = self.model(song)
        song_embedding = frame_embeddings.mean(axis=0)
        return song_embedding

    def _flush(self, buffer: list[EmbeddingWithMetadata]) -> None:
        """Flush buffer to output queue"""
        for item in buffer:
            self.output_queue.put(item)