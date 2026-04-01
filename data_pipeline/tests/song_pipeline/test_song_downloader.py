import pytest
import threading
from unittest.mock import MagicMock, patch
from pathlib import Path
from queue import Queue

from data_pipeline.song_pipeline.song_downloader import SongDownloader, DOWNLOADS_DIR
from data_pipeline.models.datamodels import AlbumMetadata, AudioWithMetadata


@pytest.fixture
def stop_event():
    return threading.Event()


@pytest.fixture
def mock_db_manager():
    """Create a mock DatabaseManager."""
    with patch('data_pipeline.song_pipeline.song_downloader.DatabaseManager') as MockDB:
        mock_instance = MagicMock()
        MockDB.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def output_queue():
    return Queue()


@pytest.fixture
def downloader(mock_db_manager, output_queue, stop_event):
    return SongDownloader(output_queue, stop_event)


class TestGetAlbumsToDownload:
    def test_get_albums_to_download_returns_results(self, downloader, mock_db_manager):
        mock_db_manager.execute_query.return_value = [
            (1, "Album One", "Artist One", "http://example.com/album1"),
            (2, "Album Two", "Artist Two", "http://example.com/album2"),
        ]

        results = downloader._get_albums_to_download()

        assert len(results) == 2
        assert results[0] == (1, "Album One", "Artist One", "http://example.com/album1")
        mock_db_manager.execute_query.assert_called_once()

    def test_get_albums_to_download_queries_pending_and_in_progress(self, downloader, mock_db_manager):
        mock_db_manager.execute_query.return_value = []

        downloader._get_albums_to_download()

        query = mock_db_manager.execute_query.call_args[0][0]
        assert "pending" in query
        assert "in_progress" in query

    def test_get_albums_to_download_uses_update_returning(self, downloader, mock_db_manager):
        mock_db_manager.execute_query.return_value = []

        downloader._get_albums_to_download()

        query = mock_db_manager.execute_query.call_args[0][0].upper()
        assert "UPDATE" in query
        assert "RETURNING" in query

    def test_get_albums_to_download_empty(self, downloader, mock_db_manager):
        mock_db_manager.execute_query.return_value = []

        results = downloader._get_albums_to_download()

        assert results == []

    def test_get_albums_to_download_uses_limit(self, downloader, mock_db_manager):
        mock_db_manager.execute_query.return_value = []

        downloader._get_albums_to_download()

        query = mock_db_manager.execute_query.call_args[0][0].upper()
        assert "LIMIT" in query


class TestDownloadSongs:
    def test_download_songs_creates_directory(self, downloader, tmp_path):
        album_id = 123
        url = "http://example.com/album"

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run'):
                downloader._download_songs(album_id, url)

        assert (tmp_path / str(album_id)).exists()

    def test_download_songs_calls_bandcamp_dl(self, downloader, tmp_path):
        album_id = 456
        url = "http://bandcamp.com/album"

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run') as mock_run:
                downloader._download_songs(album_id, url)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "bandcamp-dl"
        assert "--base-dir" in call_args
        assert url in call_args

    def test_download_songs_returns_audio_paths(self, downloader, tmp_path):
        album_id = 789
        album_dir = tmp_path / str(album_id)
        album_dir.mkdir(parents=True)
        (album_dir / "track1.mp3").touch()
        (album_dir / "track2.flac").touch()
        (album_dir / "track3.wav").touch()

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run'):
                result = downloader._download_songs(album_id, "http://example.com")

        assert len(result) == 3
        assert all(isinstance(p, Path) for p in result)

    def test_download_songs_filters_non_audio(self, downloader, tmp_path):
        album_id = 101
        album_dir = tmp_path / str(album_id)
        album_dir.mkdir(parents=True)
        (album_dir / "track1.mp3").touch()
        (album_dir / "cover.jpg").touch()
        (album_dir / "info.txt").touch()
        (album_dir / "track2.flac").touch()

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run'):
                result = downloader._download_songs(album_id, "http://example.com")

        assert len(result) == 2
        assert {p.suffix for p in result} == {'.mp3', '.flac'}

    def test_download_songs_finds_nested_audio_files(self, downloader, tmp_path):
        album_id = 202
        nested_dir = tmp_path / str(album_id) / "Artist" / "Album"
        nested_dir.mkdir(parents=True)
        (nested_dir / "01 - Track One.mp3").touch()
        (nested_dir / "02 - Track Two.mp3").touch()

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run'):
                result = downloader._download_songs(album_id, "http://example.com")

        assert len(result) == 2


class TestRun:
    def test_run_puts_items_in_queue(self, mock_db_manager, output_queue, stop_event, tmp_path):
        mock_db_manager.execute_query.return_value = [
            (1, "Test Album", "Test Artist", "http://example.com/album"),
        ]
        album_dir = tmp_path / "1"
        album_dir.mkdir(parents=True)
        (album_dir / "01 - track.mp3").touch()

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run'):
                downloader = SongDownloader(output_queue, stop_event)
                downloader.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        assert len(items) == 2
        assert isinstance(items[0], AudioWithMetadata)
        assert items[0].metadata.album_id == 1
        assert items[0].metadata.title == "Test Album"
        assert items[-1] is None

    def test_run_sends_termination_signal(self, mock_db_manager, output_queue, stop_event):
        mock_db_manager.execute_query.return_value = []

        with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run'):
            downloader = SongDownloader(output_queue, stop_event)
            downloader.run()

        assert output_queue.get() is None

    def test_run_handles_empty_album_list(self, mock_db_manager, output_queue, stop_event):
        mock_db_manager.execute_query.return_value = []

        with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run') as mock_run:
            downloader = SongDownloader(output_queue, stop_event)
            downloader.run()

        mock_run.assert_not_called()

    def test_run_processes_multiple_albums(self, mock_db_manager, output_queue, stop_event, tmp_path):
        mock_db_manager.execute_query.return_value = [
            (1, "Album One", "Artist One", "http://example.com/album1"),
            (2, "Album Two", "Artist Two", "http://example.com/album2"),
        ]
        for album_id in [1, 2]:
            album_dir = tmp_path / str(album_id)
            album_dir.mkdir(parents=True)
            (album_dir / "01 - track.mp3").touch()

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run'):
                downloader = SongDownloader(output_queue, stop_event)
                downloader.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        assert len(items) == 3  # 2 audio items + None
        assert items[-1] is None

    def test_run_stops_early_when_stop_event_set(self, mock_db_manager, output_queue, stop_event, tmp_path):
        mock_db_manager.execute_query.return_value = [
            (1, "Album One", "Artist One", "http://example.com/album1"),
            (2, "Album Two", "Artist Two", "http://example.com/album2"),
        ]
        stop_event.set()

        with patch('data_pipeline.song_pipeline.song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('data_pipeline.song_pipeline.song_downloader.subprocess.run') as mock_run:
                downloader = SongDownloader(output_queue, stop_event)
                downloader.run()

        mock_run.assert_not_called()
        assert output_queue.get() is None  # termination signal still sent
