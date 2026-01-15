import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from queue import Queue
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "local" / "2_song_ingest_process_store"))

from local.tools.datamodels import AlbumMetadata, EmbeddingWithMetadata


@pytest.fixture
def mock_db_manager():
    """Create a mock DatabaseManager."""
    with patch('song_dbwriter.DatabaseManager') as MockDB:
        mock_instance = MagicMock()
        MockDB.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def embed_queue():
    return Queue()


@pytest.fixture
def db_writer(mock_db_manager, embed_queue):
    """Create a SongDBWriter with mocked dependencies."""
    from song_dbwriter import SongDBWriter
    return SongDBWriter(embed_queue, batch_size=2)


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


class TestFlush:
    def test_flush_calls_insert_rows(self, db_writer, mock_db_manager, sample_embedding_with_metadata):
        buffer = [sample_embedding_with_metadata]

        db_writer._flush(buffer)

        mock_db_manager.insert_rows.assert_called_once()
        call_args = mock_db_manager.insert_rows.call_args
        assert call_args[0][0] == "songs"  # table name
        assert call_args[0][1] == ["album_id", "title", "artist_name", "album_name", "embedding"]

    def test_flush_extracts_song_title_from_path(self, db_writer, mock_db_manager, sample_metadata, tmp_path):
        # File path stem should become the song title
        embedding = EmbeddingWithMetadata(
            file_path=tmp_path / "03 - My Song Title.mp3",
            embedding=np.random.rand(1280),
            metadata=sample_metadata
        )

        db_writer._flush([embedding])

        call_args = mock_db_manager.insert_rows.call_args
        rows = call_args[0][2]
        assert rows[0][1] == "03 - My Song Title"  # song title from stem

    def test_flush_converts_embedding_to_list(self, db_writer, mock_db_manager, sample_metadata, tmp_path):
        embedding_array = np.array([1.0, 2.0, 3.0])
        embedding = EmbeddingWithMetadata(
            file_path=tmp_path / "track.mp3",
            embedding=embedding_array,
            metadata=sample_metadata
        )

        db_writer._flush([embedding])

        call_args = mock_db_manager.insert_rows.call_args
        rows = call_args[0][2]
        # Embedding should be converted to list
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
            file_path=tmp_path / "track.mp3",
            embedding=np.random.rand(1280),
            metadata=metadata
        )

        db_writer._flush([embedding])

        call_args = mock_db_manager.insert_rows.call_args
        rows = call_args[0][2]
        row = rows[0]
        assert row[0] == 42  # album_id
        assert row[2] == "Artist Name Here"  # artist_name
        assert row[3] == "Album Title Here"  # album_name (from metadata.title)

    def test_flush_handles_multiple_items(self, db_writer, mock_db_manager, sample_metadata, tmp_path):
        embeddings = [
            EmbeddingWithMetadata(
                file_path=tmp_path / f"track{i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            )
            for i in range(3)
        ]

        db_writer._flush(embeddings)

        call_args = mock_db_manager.insert_rows.call_args
        rows = call_args[0][2]
        assert len(rows) == 3


class TestRun:
    def test_run_processes_queue_items(self, mock_db_manager, embed_queue, sample_embedding_with_metadata):
        from song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, batch_size=10)

        embed_queue.put(sample_embedding_with_metadata)
        embed_queue.put(None)

        db_writer.run()

        # Should have called insert_rows once for the remaining buffer
        mock_db_manager.insert_rows.assert_called_once()

    def test_run_respects_batch_size(self, mock_db_manager, embed_queue, sample_metadata, tmp_path):
        from song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, batch_size=2)

        # Add 5 items - should trigger 2 flushes during run + 1 at end
        for i in range(5):
            embed_queue.put(EmbeddingWithMetadata(
                file_path=tmp_path / f"track{i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            ))
        embed_queue.put(None)

        db_writer.run()

        # batch_size=2, 5 items: flush at 2, flush at 4, flush remaining 1
        assert mock_db_manager.insert_rows.call_count == 3

    def test_run_flushes_remaining_on_termination(self, mock_db_manager, embed_queue, sample_metadata, tmp_path):
        from song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, batch_size=100)  # Large batch

        # Add only 2 items
        for i in range(2):
            embed_queue.put(EmbeddingWithMetadata(
                file_path=tmp_path / f"track{i}.mp3",
                embedding=np.random.rand(1280),
                metadata=sample_metadata
            ))
        embed_queue.put(None)

        db_writer.run()

        # Should still flush the partial batch
        mock_db_manager.insert_rows.assert_called_once()
        rows = mock_db_manager.insert_rows.call_args[0][2]
        assert len(rows) == 2

    def test_run_handles_empty_queue(self, mock_db_manager, embed_queue):
        from song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, batch_size=10)

        embed_queue.put(None)  # Immediate termination

        db_writer.run()

        # Should not call insert_rows if buffer is empty
        mock_db_manager.insert_rows.assert_not_called()

    def test_run_connects_to_database(self, mock_db_manager, embed_queue):
        from song_dbwriter import SongDBWriter
        db_writer = SongDBWriter(embed_queue, batch_size=10)

        # Connection happens in __init__
        mock_db_manager.connect.assert_called_once()
