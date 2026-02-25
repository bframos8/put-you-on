import pytest
from unittest.mock import MagicMock, patch
from queue import Queue
import numpy as np
import sys

# Must mock essentia BEFORE importing any pipeline modules that import it
mock_loader_instance = MagicMock()
mock_loader_instance.return_value = np.zeros(16000)

mock_model_instance = MagicMock()
mock_model_instance.return_value = np.random.rand(10, 1280)

mock_essentia_standard = MagicMock()
mock_essentia_standard.MonoLoader.return_value = mock_loader_instance
mock_essentia_standard.TensorflowPredictEffnetDiscogs.return_value = mock_model_instance

sys.modules['essentia'] = MagicMock()
sys.modules['essentia.standard'] = mock_essentia_standard

from data_pipeline.tools.datamodels import AlbumMetadata, AudioWithMetadata, EmbeddingWithMetadata


@pytest.fixture
def mock_all_external_deps(tmp_path):
    """Mock all external dependencies for integration testing."""
    with patch('data_pipeline.song_pipeline.song_downloader.DatabaseManager') as MockDownloaderDB, \
         patch('data_pipeline.song_pipeline.song_downloader.subprocess.run') as mock_subprocess, \
         patch('data_pipeline.song_pipeline.song_dbwriter.DatabaseManager') as MockWriterDB:

        mock_downloader_db = MagicMock()
        mock_downloader_db.execute_query.return_value = [
            (1, "Test Album", "Test Artist", "http://example.com/album"),
        ]
        MockDownloaderDB.return_value = mock_downloader_db

        def create_fake_files(*args, **kwargs):
            album_dir = tmp_path / "downloads" / "1"
            album_dir.mkdir(parents=True, exist_ok=True)
            (album_dir / "01 - Track One.mp3").touch()
            (album_dir / "02 - Track Two.mp3").touch()
        mock_subprocess.side_effect = create_fake_files

        mock_writer_db = MagicMock()
        MockWriterDB.return_value = mock_writer_db

        yield {
            'downloader_db': mock_downloader_db,
            'subprocess': mock_subprocess,
            'writer_db': mock_writer_db,
            'tmp_path': tmp_path,
        }


class TestFullPipelineFlow:
    def test_data_flows_through_all_stages(self, mock_all_external_deps, tmp_path):
        from data_pipeline.song_pipeline.song_downloader import SongDownloader
        from data_pipeline.song_pipeline.song_embedder import SongEmbedder
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
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
            writer_db.insert_rows.assert_called_once()

            call_args = writer_db.insert_rows.call_args
            assert call_args[0][0] == "songs"
            assert call_args[0][1] == ["album_id", "title", "artist_name", "album_title", "embedding"]

            rows = call_args[0][2]
            assert len(rows) == 2  # Two tracks
            for row in rows:
                assert row[0] == 1                 # album_id
                assert row[2] == "Test Artist"     # artist_name
                assert row[3] == "Test Album"      # album_title
                assert len(row[4]) == 1280         # embedding dimension

    def test_termination_signals_propagate(self, mock_all_external_deps, tmp_path):
        from data_pipeline.song_pipeline.song_downloader import SongDownloader
        from data_pipeline.song_pipeline.song_embedder import SongEmbedder
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter

        mock_all_external_deps['downloader_db'].execute_query.return_value = []

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
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

            assert not downloader.is_alive()
            assert not embedder.is_alive()
            assert not db_writer.is_alive()

    def test_pipeline_handles_empty_input(self, mock_all_external_deps, tmp_path):
        from data_pipeline.song_pipeline.song_downloader import SongDownloader
        from data_pipeline.song_pipeline.song_embedder import SongEmbedder
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter

        mock_all_external_deps['downloader_db'].execute_query.return_value = []

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
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

            mock_all_external_deps['writer_db'].insert_rows.assert_not_called()


class TestPipelineDataIntegrity:
    def test_metadata_preserved_through_pipeline(self, mock_all_external_deps, tmp_path):
        from data_pipeline.song_pipeline.song_downloader import SongDownloader
        from data_pipeline.song_pipeline.song_embedder import SongEmbedder
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter

        mock_all_external_deps['downloader_db'].execute_query.return_value = [
            (999, "Unique Album Name", "Unique Artist", "http://unique.com"),
        ]

        def create_single_file(*args, **kwargs):
            album_dir = tmp_path / "downloads" / "999"
            album_dir.mkdir(parents=True, exist_ok=True)
            (album_dir / "01 - Single Track.mp3").touch()
        mock_all_external_deps['subprocess'].side_effect = create_single_file

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
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

            rows = mock_all_external_deps['writer_db'].insert_rows.call_args[0][2]
            assert len(rows) == 1
            row = rows[0]
            assert row[0] == 999                   # album_id preserved
            assert row[1] == "Single track"        # title extracted from filename
            assert row[2] == "Unique Artist"       # artist_name preserved
            assert row[3] == "Unique Album Name"   # album_title preserved

    def test_pipeline_handles_multiple_albums(self, mock_all_external_deps, tmp_path):
        from data_pipeline.song_pipeline.song_downloader import SongDownloader
        from data_pipeline.song_pipeline.song_embedder import SongEmbedder
        from data_pipeline.song_pipeline.song_dbwriter import SongDBWriter

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
            (album_dir / f"01 - track from album {album_id}.mp3").touch()
        mock_all_external_deps['subprocess'].side_effect = create_files_for_album

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path / "downloads"):
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

            rows = mock_all_external_deps['writer_db'].insert_rows.call_args[0][2]
            assert len(rows) == 2
            assert {row[0] for row in rows} == {1, 2}
