import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from queue import Queue
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "local" / "2_song_ingest_process_store"))

from local.tools.datamodels import AlbumMetadata, AudioWithMetadata, EmbeddingWithMetadata


@pytest.fixture
def input_queue():
    return Queue()


@pytest.fixture
def output_queue():
    return Queue()


@pytest.fixture
def mock_essentia():
    """Mock essentia MonoLoader and TensorflowPredictEffnetDiscogs."""
    with patch('song_embedder.MonoLoader') as MockLoader, \
         patch('song_embedder.TensorflowPredictEffnetDiscogs') as MockModel:

        mock_loader_instance = MagicMock()
        mock_loader_instance.return_value = np.zeros(16000)  # 1 second of audio at 16kHz
        MockLoader.return_value = mock_loader_instance

        mock_model_instance = MagicMock()
        # Model returns frame embeddings (e.g., 10 frames x 1280 dimensions)
        mock_model_instance.return_value = np.random.rand(10, 1280)
        MockModel.return_value = mock_model_instance

        yield {
            'loader_class': MockLoader,
            'loader_instance': mock_loader_instance,
            'model_class': MockModel,
            'model_instance': mock_model_instance,
        }


@pytest.fixture
def embedder(mock_essentia, input_queue, output_queue):
    """Create a SongEmbedder with mocked dependencies."""
    from song_embedder import SongEmbedder
    return SongEmbedder(input_queue, output_queue, batch_size=2)


@pytest.fixture
def sample_metadata():
    return AlbumMetadata(
        album_id=1,
        title="Test Album",
        artist_name="Test Artist",
        url="http://example.com/album"
    )


@pytest.fixture
def sample_audio_with_metadata(sample_metadata, tmp_path):
    audio_file = tmp_path / "test_track.mp3"
    audio_file.touch()
    return AudioWithMetadata(
        file_path=audio_file,
        metadata=sample_metadata
    )


class TestLoadSong:
    def test_load_song(self, embedder, mock_essentia, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.touch()

        result = embedder._load_song(str(audio_file))

        mock_essentia['loader_instance'].assert_called_once_with(
            filename=str(audio_file),
            samplerate=16000,
            resampleQuality=4
        )
        assert isinstance(result, np.ndarray)


class TestEmbedSong:
    def test_embed_song(self, embedder, mock_essentia):
        # Create fake audio data
        audio = np.zeros(16000)

        result = embedder._embed_song(audio)

        mock_essentia['model_instance'].assert_called_once_with(audio)
        # Result should be mean of frame embeddings (1280 dimensions)
        assert result.shape == (1280,)

    def test_embed_song_computes_mean(self, embedder, mock_essentia):
        # Set up specific frame embeddings to verify mean computation
        frame_embeddings = np.array([
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
        ])
        mock_essentia['model_instance'].return_value = frame_embeddings

        audio = np.zeros(16000)
        result = embedder._embed_song(audio)

        expected = np.array([2.5, 3.5, 4.5])
        np.testing.assert_array_equal(result, expected)


class TestFlush:
    def test_flush_puts_items_in_output_queue(self, embedder, output_queue, sample_metadata, tmp_path):
        items = [
            EmbeddingWithMetadata(
                file_path=tmp_path / "track1.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            ),
            EmbeddingWithMetadata(
                file_path=tmp_path / "track2.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            ),
        ]

        embedder._flush(items)

        assert output_queue.qsize() == 2


class TestRun:
    def test_run_processes_queue_items(self, mock_essentia, input_queue, output_queue, sample_audio_with_metadata):
        from song_embedder import SongEmbedder
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16)

        input_queue.put(sample_audio_with_metadata)
        input_queue.put(None)  # Termination signal

        embedder.run()

        # Should have 1 embedding + 1 None
        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        assert len(items) == 2
        assert isinstance(items[0], EmbeddingWithMetadata)
        assert items[0].metadata.album_id == 1
        assert items[1] is None

    def test_run_respects_batch_size(self, mock_essentia, input_queue, output_queue, sample_metadata, tmp_path):
        from song_embedder import SongEmbedder
        embedder = SongEmbedder(input_queue, output_queue, batch_size=2)

        # Add 3 items - should flush after 2, then flush remaining 1
        for i in range(3):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        # 3 embeddings + 1 None
        assert len(items) == 4
        assert items[-1] is None

    def test_run_flushes_remaining_on_termination(self, mock_essentia, input_queue, output_queue, sample_metadata, tmp_path):
        from song_embedder import SongEmbedder
        embedder = SongEmbedder(input_queue, output_queue, batch_size=10)  # Large batch size

        # Add only 2 items (less than batch size)
        for i in range(2):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        # Should still get all items even though batch wasn't full
        assert len(items) == 3  # 2 embeddings + 1 None

    def test_run_sends_termination_signal(self, mock_essentia, input_queue, output_queue):
        from song_embedder import SongEmbedder
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16)

        input_queue.put(None)  # Immediate termination

        embedder.run()

        assert output_queue.get() is None

    def test_run_preserves_metadata(self, mock_essentia, input_queue, output_queue, tmp_path):
        from song_embedder import SongEmbedder
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16)

        metadata = AlbumMetadata(
            album_id=42,
            title="Specific Album",
            artist_name="Specific Artist",
            url="http://specific.com"
        )
        audio_file = tmp_path / "track.mp3"
        audio_file.touch()

        input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=metadata))
        input_queue.put(None)

        embedder.run()

        result = output_queue.get()
        assert result.metadata.album_id == 42
        assert result.metadata.title == "Specific Album"
        assert result.metadata.artist_name == "Specific Artist"
        assert result.file_path == audio_file
