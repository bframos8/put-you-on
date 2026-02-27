import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from queue import Queue
import numpy as np
import sys

# Must mock essentia BEFORE importing song_embedder since it's imported at module level
mock_loader_instance = MagicMock()
mock_loader_instance.return_value = np.zeros(16000)

mock_model_instance = MagicMock()
mock_model_instance.return_value = np.random.rand(10, 1280)

mock_essentia_standard = MagicMock()
mock_essentia_standard.MonoLoader.return_value = mock_loader_instance
mock_essentia_standard.TensorflowPredictEffnetDiscogs.return_value = mock_model_instance

sys.modules['essentia'] = MagicMock()
sys.modules['essentia.standard'] = mock_essentia_standard

from data_pipeline.models.datamodels import AlbumMetadata, AudioWithMetadata, EmbeddingWithMetadata
from data_pipeline.song_pipeline.song_embedder import SongEmbedder


@pytest.fixture
def input_queue():
    return Queue()


@pytest.fixture
def output_queue():
    return Queue()


@pytest.fixture
def mock_essentia():
    """Reset mock call counts for each test."""
    mock_loader_instance.reset_mock()
    mock_model_instance.reset_mock()
    mock_essentia_standard.MonoLoader.reset_mock()
    mock_essentia_standard.TensorflowPredictEffnetDiscogs.reset_mock()

    mock_loader_instance.return_value = np.zeros(16000)
    mock_model_instance.return_value = np.random.rand(10, 1280)

    return {
        'loader_class': mock_essentia_standard.MonoLoader,
        'loader_instance': mock_loader_instance,
        'model_class': mock_essentia_standard.TensorflowPredictEffnetDiscogs,
        'model_instance': mock_model_instance,
    }


@pytest.fixture
def embedder(mock_essentia, input_queue, output_queue):
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
    return AudioWithMetadata(file_path=audio_file, metadata=sample_metadata)


class TestLoadSong:
    def test_load_song_calls_mono_loader_with_correct_args(self, embedder, mock_essentia, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.touch()

        embedder._load_song(str(audio_file))

        mock_essentia['loader_class'].assert_called_once_with(
            filename=str(audio_file),
            sampleRate=16000,
            resampleQuality=4
        )

    def test_load_song_returns_audio_array(self, embedder, mock_essentia, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.touch()

        result = embedder._load_song(str(audio_file))

        assert isinstance(result, np.ndarray)


class TestEmbedSong:
    def test_embed_song_calls_model(self, embedder, mock_essentia):
        audio = np.zeros(16000)

        embedder._embed_song(audio)

        mock_essentia['model_instance'].assert_called_once_with(audio)

    def test_embed_song_returns_mean_of_frames(self, embedder, mock_essentia):
        frame_embeddings = np.array([
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
        ])
        mock_essentia['model_instance'].return_value = frame_embeddings

        result = embedder._embed_song(np.zeros(16000))

        np.testing.assert_array_equal(result, np.array([2.5, 3.5, 4.5]))

    def test_embed_song_output_shape(self, embedder, mock_essentia):
        audio = np.zeros(16000)

        result = embedder._embed_song(audio)

        assert result.shape == (1280,)


class TestFlush:
    def test_flush_puts_all_items_in_output_queue(self, embedder, output_queue, sample_metadata, tmp_path):
        items = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"track{i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            )
            for i in range(3)
        ]

        embedder._flush(items)

        assert output_queue.qsize() == 3

    def test_flush_preserves_item_order(self, embedder, output_queue, sample_metadata, tmp_path):
        embeddings = [np.array([float(i)] * 1280) for i in range(3)]
        items = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"track{i}.mp3",
                embedding=embeddings[i],
                metadata=sample_metadata
            )
            for i in range(3)
        ]

        embedder._flush(items)

        for i in range(3):
            result = output_queue.get()
            np.testing.assert_array_equal(result.embedding, embeddings[i])


class TestRun:
    def test_run_processes_single_item(self, mock_essentia, input_queue, output_queue, sample_audio_with_metadata):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16)
        input_queue.put(sample_audio_with_metadata)
        input_queue.put(None)

        embedder.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        assert len(items) == 2  # 1 embedding + None
        assert isinstance(items[0], EmbeddingWithMetadata)
        assert items[0].metadata.album_id == 1
        assert items[-1] is None

    def test_run_sends_termination_signal(self, mock_essentia, input_queue, output_queue):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16)
        input_queue.put(None)

        embedder.run()

        assert output_queue.get() is None

    def test_run_flushes_remaining_on_termination(self, mock_essentia, input_queue, output_queue, sample_metadata, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=100)
        for i in range(2):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        assert len(items) == 3  # 2 embeddings + None

    def test_run_respects_batch_size(self, mock_essentia, input_queue, output_queue, sample_metadata, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=2)
        for i in range(3):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        assert len(items) == 4  # 3 embeddings + None

    def test_run_preserves_metadata(self, mock_essentia, input_queue, output_queue, tmp_path):
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
