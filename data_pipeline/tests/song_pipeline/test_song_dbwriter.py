import pytest
import threading
from unittest.mock import MagicMock, patch
from queue import Queue
import numpy as np

from data_pipeline.models.datamodels import AlbumMetadata, EmbeddingWithMetadata


@pytest.fixture
def stop_event():
    return threading.Event()


@pytest.fixture(autouse=True)
def mock_file_deletion():
    """Prevent _delete_processed_songs from trying to remove non-existent test files."""
    with patch('data_pipeline.song_pipeline.song_dbwriter.os.remove'):
        yield


@pytest.fixture
def mock_db_manager():
    with patch('data_pipeline.song_pipeline.song_dbwriter.DatabaseManager') as MockDB:
        mock_instance = MagicMock()
        MockDB.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def embed_queue():
    return Queue()


@pytest.fixture
def db_writer(mock_db_manager, embed_queue, stop_event):
    from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
    return SongDBWriter(embed_queue, stop_event)


@pytest.fixture
def sample_metadata():
    return AlbumMetadata(
        album_id=1,
        title="Test Album",
        artist_name="Test Artist",
        url="http://example.com/album"
    )


@pytest.fixture
def sample_embedding_with_metadata(sample_metadata, tmp_path):
    return EmbeddingWithMetadata(
        file_path=tmp_path / "01 - Test Track.mp3",
        embedding=np.random.rand(1280),
        metadata=sample_metadata
    )


class TestExtractName:
    def test_extracts_title_from_numbered_filename(self, db_writer):
        assert db_writer._extract_name("01 - My Song Title") == "My song title"

    def test_extracts_title_without_hyphen(self, db_writer):
        assert db_writer._extract_name("03  Track Name") == "Track name"

    def test_replaces_hyphens_in_title(self, db_writer):
        assert db_writer._extract_name("02 - Some-Hyphenated-Title") == "Some hyphenated title"

    def test_capitalizes_first_letter_only(self, db_writer):
        result = db_writer._extract_name("05 - ALL CAPS TITLE")
        assert result[0].isupper()
        assert result[1:].islower()


class TestFlush:
    def test_flush_calls_insert_rows_on_songs_table(self, db_writer, mock_db_manager, sample_embedding_with_metadata):
        db_writer._flush([sample_embedding_with_metadata])

        mock_db_manager.insert_rows_ignore_conflicts.assert_called_once()
        call_args = mock_db_manager.insert_rows_ignore_conflicts.call_args
        assert call_args[0][0] == "songs"

    def test_flush_uses_correct_column_names(self, db_writer, mock_db_manager, sample_embedding_with_metadata):
        db_writer._flush([sample_embedding_with_metadata])

        call_args = mock_db_manager.insert_rows_ignore_conflicts.call_args
        assert call_args[0][1] == ["album_id", "title", "artist_name", "album_title", "embedding"]

    def test_flush_extracts_song_title_from_filename(self, db_writer, mock_db_manager, sample_metadata, tmp_path):
        embedding = EmbeddingWithMetadata(
            file_path=tmp_path / "03 - My Song Title.mp3",
            embedding=np.random.rand(1280),
            metadata=sample_metadata
        )

        db_writer._flush([embedding])

        rows = mock_db_manager.insert_rows_ignore_conflicts.call_args[0][2]
        assert rows[0][1] == "My song title"

    def test_flush_converts_embedding_to_list(self, db_writer, mock_db_manager, sample_metadata, tmp_path):
        embedding_array = np.array([1.0, 2.0, 3.0])
        embedding = EmbeddingWithMetadata(
            file_path=tmp_path / "01 - test track.mp3",
            embedding=embedding_array,
            metadata=sample_metadata
        )

        db_writer._flush([embedding])

        rows = mock_db_manager.insert_rows_ignore_conflicts.call_args[0][2]
        assert rows[0][4] == [1.0, 2.0, 3.0]
        assert isinstance(rows[0][4], list)

    def test_flush_includes_correct_metadata(self, db_writer, mock_db_manager, tmp_path):
        metadata = AlbumMetadata(
            album_id=42,
            title="Album Title Here",
            artist_name="Artist Name Here",
            url="http://example.com"
        )
        embedding = EmbeddingWithMetadata(
            file_path=tmp_path / "01 - some song.mp3",
            embedding=np.random.rand(1280),
            metadata=metadata
        )

        db_writer._flush([embedding])

        row = mock_db_manager.insert_rows_ignore_conflicts.call_args[0][2][0]
        assert row[0] == 42
        assert row[2] == "Artist Name Here"
        assert row[3] == "Album Title Here"

    def test_flush_handles_multiple_items(self, db_writer, mock_db_manager, sample_metadata, tmp_path):
        embeddings = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"0{i+1} - track {i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            )
            for i in range(3)
        ]

        db_writer._flush(embeddings)

        rows = mock_db_manager.insert_rows_ignore_conflicts.call_args[0][2]
        assert len(rows) == 3

    def test_flush_marks_albums_as_completed(self, db_writer, mock_db_manager, tmp_path):
        embeddings = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"0{i+1} - track {i}.mp3",
                embedding=np.random.rand(1280),
                metadata=AlbumMetadata(album_id=i, title="T", artist_name="A", url="u")
            )
            for i in range(2)
        ]

        db_writer._flush(embeddings)

        mock_db_manager.update_rows_by_ids.assert_called_once()
        call_args = mock_db_manager.update_rows_by_ids.call_args[0]
        assert call_args[0] == "albums"
        assert call_args[2] == "completed"
        assert set(call_args[3]) == {0, 1}


class TestRun:
    def test_run_processes_batch_from_queue(self, mock_db_manager, embed_queue, stop_event, sample_embedding_with_metadata):
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, stop_event)

        embed_queue.put([sample_embedding_with_metadata])
        embed_queue.put(None)

        db_writer.run()

        mock_db_manager.insert_rows_ignore_conflicts.assert_called_once()

    def test_run_calls_flush_once_per_batch(self, mock_db_manager, embed_queue, stop_event, sample_metadata, tmp_path):
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, stop_event)

        batch1 = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"0{i+1} - track {i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            )
            for i in range(3)
        ]
        batch2 = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"1{i+1} - track {i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            )
            for i in range(2)
        ]
        embed_queue.put(batch1)
        embed_queue.put(batch2)
        embed_queue.put(None)

        db_writer.run()

        assert mock_db_manager.insert_rows_ignore_conflicts.call_count == 2

    def test_run_handles_empty_queue(self, mock_db_manager, embed_queue, stop_event):
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, stop_event)

        embed_queue.put(None)

        db_writer.run()

        mock_db_manager.insert_rows_ignore_conflicts.assert_not_called()

    def test_run_connects_to_database_on_init(self, mock_db_manager, embed_queue, stop_event):
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
        SongDBWriter(embed_queue, stop_event)

        mock_db_manager.connect.assert_called_once()

    def test_run_stores_error_on_failure(self, mock_db_manager, embed_queue, stop_event, sample_embedding_with_metadata):
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, stop_event)
        mock_db_manager.insert_rows_ignore_conflicts.side_effect = RuntimeError("DB down")

        embed_queue.put([sample_embedding_with_metadata])
        embed_queue.put(None)

        db_writer.run()

        assert db_writer.error is not None
        assert stop_event.is_set()
