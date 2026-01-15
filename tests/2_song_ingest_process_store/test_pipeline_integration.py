import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from queue import Queue
import numpy as np
import threading
import time

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "local" / "2_song_ingest_process_store"))

from local.tools.datamodels import AlbumMetadata, AudioWithMetadata, EmbeddingWithMetadata


@pytest.fixture
def mock_all_external_deps(tmp_path):
    """Mock all external dependencies for integration testing."""
    with patch('song_downloader.DatabaseManager') as MockDownloaderDB, \
         patch('song_downloader.subprocess.run') as mock_subprocess, \
         patch('song_embedder.MonoLoader') as MockLoader, \
         patch('song_embedder.TensorflowPredictEffnetDiscogs') as MockModel, \
         patch('song_dbwriter.DatabaseManager') as MockWriterDB:

        # Setup downloader DB mock
        mock_downloader_db = MagicMock()
        mock_downloader_db.execute_query.return_value = [
            (1, "Test Album", "Test Artist", "http://example.com/album"),
        ]
        MockDownloaderDB.return_value = mock_downloader_db

        # Setup subprocess mock to create fake audio files
        def create_fake_files(*args, **kwargs):
            album_dir = tmp_path / "downloads" / "1"
            album_dir.mkdir(parents=True, exist_ok=True)
            (album_dir / "01 - Track One.mp3").touch()
            (album_dir / "02 - Track Two.mp3").touch()
        mock_subprocess.side_effect = create_fake_files

        # Setup embedder mocks
        mock_loader = MagicMock()
        mock_loader.return_value = np.zeros(16000)
        MockLoader.return_value = mock_loader

        mock_model = MagicMock()
        mock_model.return_value = np.random.rand(10, 1280)
        MockModel.return_value = mock_model

        # Setup writer DB mock
        mock_writer_db = MagicMock()
        MockWriterDB.return_value = mock_writer_db

        yield {
            'downloader_db': mock_downloader_db,
            'subprocess': mock_subprocess,
            'loader': mock_loader,
            'model': mock_model,
            'writer_db': mock_writer_db,
            'tmp_path': tmp_path,
        }


class TestFullPipelineFlow:
    def test_full_pipeline_flow(self, mock_all_external_deps, tmp_path):
        """Test that data flows correctly through all pipeline stages."""
        from song_downloader import SongDownloader
        from song_embedder import SongEmbedder
        from song_dbwriter import SongDBWriter

        # Patch DOWNLOADS_DIR to use tmp_path
        with patch('song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
            audio_queue = Queue(maxsize=32)
            embed_queue = Queue(maxsize=64)

            downloader = SongDownloader(audio_queue)
            embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16)
            db_writer = SongDBWriter(embed_queue, batch_size=100)

            # Run pipeline
            downloader.start()
            embedder.start()
            db_writer.start()

            downloader.join(timeout=5)
            embedder.join(timeout=5)
            db_writer.join(timeout=5)

            # Verify DB was called with correct data
            writer_db = mock_all_external_deps['writer_db']
            writer_db.insert_rows.assert_called_once()

            call_args = writer_db.insert_rows.call_args
            table_name = call_args[0][0]
            columns = call_args[0][1]
            rows = call_args[0][2]

            assert table_name == "songs"
            assert columns == ["album_id", "title", "artist_name", "album_name", "embedding"]
            assert len(rows) == 2  # Two tracks

            # Verify row content
            for row in rows:
                assert row[0] == 1  # album_id
                assert row[2] == "Test Artist"
                assert row[3] == "Test Album"
                assert len(row[4]) == 1280  # embedding dimension

    def test_pipeline_termination_signals_propagate(self, mock_all_external_deps, tmp_path):
        """Test that None signals correctly propagate through pipeline."""
        from song_downloader import SongDownloader
        from song_embedder import SongEmbedder
        from song_dbwriter import SongDBWriter

        # Empty album list - should still terminate cleanly
        mock_all_external_deps['downloader_db'].execute_query.return_value = []

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
            audio_queue = Queue(maxsize=32)
            embed_queue = Queue(maxsize=64)

            downloader = SongDownloader(audio_queue)
            embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16)
            db_writer = SongDBWriter(embed_queue, batch_size=100)

            downloader.start()
            embedder.start()
            db_writer.start()

            # All threads should terminate
            downloader.join(timeout=5)
            embedder.join(timeout=5)
            db_writer.join(timeout=5)

            assert not downloader.is_alive()
            assert not embedder.is_alive()
            assert not db_writer.is_alive()

    def test_pipeline_handles_empty_input(self, mock_all_external_deps, tmp_path):
        """Test pipeline handles case with no albums to process."""
        from song_downloader import SongDownloader
        from song_embedder import SongEmbedder
        from song_dbwriter import SongDBWriter

        mock_all_external_deps['downloader_db'].execute_query.return_value = []

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
            audio_queue = Queue(maxsize=32)
            embed_queue = Queue(maxsize=64)

            downloader = SongDownloader(audio_queue)
            embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16)
            db_writer = SongDBWriter(embed_queue, batch_size=100)

            downloader.start()
            embedder.start()
            db_writer.start()

            downloader.join(timeout=5)
            embedder.join(timeout=5)
            db_writer.join(timeout=5)

            # DB insert should not be called with empty data
            writer_db = mock_all_external_deps['writer_db']
            writer_db.insert_rows.assert_not_called()


class TestPipelineDataIntegrity:
    def test_metadata_preserved_through_pipeline(self, mock_all_external_deps, tmp_path):
        """Test that metadata is correctly preserved from download to DB write."""
        from song_downloader import SongDownloader
        from song_embedder import SongEmbedder
        from song_dbwriter import SongDBWriter

        # Set specific metadata
        mock_all_external_deps['downloader_db'].execute_query.return_value = [
            (999, "Unique Album Name", "Unique Artist", "http://unique.com"),
        ]

        def create_single_file(*args, **kwargs):
            album_dir = tmp_path / "downloads" / "999"
            album_dir.mkdir(parents=True, exist_ok=True)
            (album_dir / "Single Track.mp3").touch()
        mock_all_external_deps['subprocess'].side_effect = create_single_file

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
            audio_queue = Queue(maxsize=32)
            embed_queue = Queue(maxsize=64)

            downloader = SongDownloader(audio_queue)
            embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16)
            db_writer = SongDBWriter(embed_queue, batch_size=100)

            downloader.start()
            embedder.start()
            db_writer.start()

            downloader.join(timeout=5)
            embedder.join(timeout=5)
            db_writer.join(timeout=5)

            writer_db = mock_all_external_deps['writer_db']
            rows = writer_db.insert_rows.call_args[0][2]

            assert len(rows) == 1
            row = rows[0]
            assert row[0] == 999  # album_id preserved
            assert row[1] == "Single Track"  # song title from filename
            assert row[2] == "Unique Artist"  # artist preserved
            assert row[3] == "Unique Album Name"  # album name preserved


class TestPipelineErrorHandling:
    def test_pipeline_with_multiple_albums(self, mock_all_external_deps, tmp_path):
        """Test pipeline handles multiple albums correctly."""
        from song_downloader import SongDownloader
        from song_embedder import SongEmbedder
        from song_dbwriter import SongDBWriter

        mock_all_external_deps['downloader_db'].execute_query.return_value = [
            (1, "Album One", "Artist One", "http://example.com/1"),
            (2, "Album Two", "Artist Two", "http://example.com/2"),
        ]

        call_count = [0]
        def create_files_for_album(*args, **kwargs):
            call_count[0] += 1
            album_id = call_count[0]
            album_dir = tmp_path / "downloads" / str(album_id)
            album_dir.mkdir(parents=True, exist_ok=True)
            (album_dir / f"track_from_album_{album_id}.mp3").touch()
        mock_all_external_deps['subprocess'].side_effect = create_files_for_album

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
            audio_queue = Queue(maxsize=32)
            embed_queue = Queue(maxsize=64)

            downloader = SongDownloader(audio_queue)
            embedder = SongEmbedder(audio_queue, embed_queue, batch_size=16)
            db_writer = SongDBWriter(embed_queue, batch_size=100)

            downloader.start()
            embedder.start()
            db_writer.start()

            downloader.join(timeout=5)
            embedder.join(timeout=5)
            db_writer.join(timeout=5)

            writer_db = mock_all_external_deps['writer_db']
            rows = writer_db.insert_rows.call_args[0][2]

            assert len(rows) == 2
            album_ids = {row[0] for row in rows}
            assert album_ids == {1, 2}
