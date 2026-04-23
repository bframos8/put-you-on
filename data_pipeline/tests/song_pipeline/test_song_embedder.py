import pytest
import threading
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
def stop_event():
    return threading.Event()


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

    mock_loader_instance.side_effect = None
    mock_model_instance.side_effect = None
    mock_loader_instance.return_value = np.zeros(16000)
    mock_model_instance.return_value = np.random.rand(10, 1280)

    return {
        'loader_class': mock_essentia_standard.MonoLoader,
        'loader_instance': mock_loader_instance,
        'model_class': mock_essentia_standard.TensorflowPredictEffnetDiscogs,
        'model_instance': mock_model_instance,
    }


@pytest.fixture
def embedder(mock_essentia, input_queue, output_queue, stop_event):
    return SongEmbedder(input_queue, output_queue, batch_size=2, stop_event=stop_event)


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

    def test_embed_song_raises_when_model_returns_empty_list(self, embedder, mock_essentia):
        mock_essentia['model_instance'].return_value = []
        audio = np.zeros(8000)

        with pytest.raises(ValueError, match="no frames"):
            embedder._embed_song(audio)

    def test_embed_song_raises_when_model_returns_non_empty_list(self, embedder, mock_essentia):
        mock_essentia['model_instance'].return_value = [[1.0, 2.0], [3.0, 4.0]]
        audio = np.zeros(8000)

        with pytest.raises(ValueError, match="no frames"):
            embedder._embed_song(audio)

    def test_embed_song_raises_when_model_returns_empty_ndarray(self, embedder, mock_essentia):
        mock_essentia['model_instance'].return_value = np.array([])
        audio = np.zeros(8000)

        with pytest.raises(ValueError, match="no frames"):
            embedder._embed_song(audio)


class TestFlush:
    def test_flush_puts_one_batch_item_in_output_queue(self, embedder, output_queue, sample_metadata, tmp_path):
        items = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"track{i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            )
            for i in range(3)
        ]

        embedder._flush(items)

        assert output_queue.qsize() == 1
        batch = output_queue.get()
        assert len(batch) == 3

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

        batch = output_queue.get()
        for i in range(3):
            np.testing.assert_array_equal(batch[i].embedding, embeddings[i])


class TestRun:
    def test_run_processes_single_item(self, mock_essentia, input_queue, output_queue, stop_event, sample_audio_with_metadata):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16, stop_event=stop_event)
        input_queue.put(sample_audio_with_metadata)
        input_queue.put(None)

        embedder.run()

        assert output_queue.qsize() == 2
        batch = output_queue.get()
        assert isinstance(batch, list)
        assert len(batch) == 1
        assert isinstance(batch[0], EmbeddingWithMetadata)
        assert batch[0].metadata.album_id == 1
        assert output_queue.get() is None

    def test_run_sends_termination_signal(self, mock_essentia, input_queue, output_queue, stop_event):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16, stop_event=stop_event)
        input_queue.put(None)

        embedder.run()

        assert output_queue.get() is None

    def test_run_flushes_remaining_on_termination(self, mock_essentia, input_queue, output_queue, stop_event, sample_metadata, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=100, stop_event=stop_event)
        for i in range(2):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        assert output_queue.qsize() == 2
        batch = output_queue.get()
        assert len(batch) == 2
        assert output_queue.get() is None

    def test_run_respects_batch_size(self, mock_essentia, input_queue, output_queue, stop_event, sample_metadata, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=2, stop_event=stop_event)
        for i in range(3):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        assert output_queue.qsize() == 3
        batch1 = output_queue.get()
        assert len(batch1) == 2
        batch2 = output_queue.get()
        assert len(batch2) == 1
        assert output_queue.get() is None

    def test_run_preserves_metadata(self, mock_essentia, input_queue, output_queue, stop_event, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16, stop_event=stop_event)
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

        batch = output_queue.get()
        result = batch[0]
        assert result.metadata.album_id == 42
        assert result.metadata.title == "Specific Album"
        assert result.metadata.artist_name == "Specific Artist"
        assert result.file_path == audio_file

    def test_run_stops_early_when_stop_event_set(self, mock_essentia, input_queue, output_queue, stop_event, sample_metadata, tmp_path):
        stop_event.set()
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16, stop_event=stop_event)
        for i in range(3):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        # Should have sent None and flushed nothing (stopped immediately)
        assert output_queue.get() is None

    def test_run_skips_track_when_model_returns_no_frames(self, mock_essentia, input_queue, output_queue, stop_event, sample_metadata, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16, stop_event=stop_event)

        short_file = tmp_path / "short.mp3"
        short_file.touch()
        normal_file = tmp_path / "normal.mp3"
        normal_file.touch()

        normal_frames = np.random.rand(10, 1280)
        return_values = [[], normal_frames]
        call_count = 0

        def side_effect(audio):
            nonlocal call_count
            val = return_values[call_count]
            call_count += 1
            return val

        mock_essentia['model_instance'].side_effect = side_effect
        input_queue.put(AudioWithMetadata(file_path=short_file, metadata=sample_metadata))
        input_queue.put(AudioWithMetadata(file_path=normal_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        batch = output_queue.get()
        assert len(batch) == 1
        assert batch[0].file_path == normal_file
        assert output_queue.get() is None

    def test_run_does_not_crash_on_skipped_track(self, mock_essentia, input_queue, output_queue, stop_event, sample_metadata, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16, stop_event=stop_event)
        mock_essentia['model_instance'].return_value = []

        for i in range(3):
            audio_file = tmp_path / f"short{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        assert embedder.error is None
        assert output_queue.get() is None  # only termination signal, no batches

    def test_run_continues_after_skipped_track(self, mock_essentia, input_queue, output_queue, stop_event, sample_metadata, tmp_path):
        embedder = SongEmbedder(input_queue, output_queue, batch_size=16, stop_event=stop_event)

        valid_frames = np.random.rand(10, 1280)
        return_values = [[], valid_frames, valid_frames]
        call_count = 0

        def side_effect(audio):
            nonlocal call_count
            val = return_values[call_count]
            call_count += 1
            return val

        mock_essentia['model_instance'].side_effect = side_effect

        for i in range(3):
            audio_file = tmp_path / f"track{i}.mp3"
            audio_file.touch()
            input_queue.put(AudioWithMetadata(file_path=audio_file, metadata=sample_metadata))
        input_queue.put(None)

        embedder.run()

        batch = output_queue.get()
        assert len(batch) == 2  # track0 skipped, track1 and track2 embedded
        assert output_queue.get() is None
