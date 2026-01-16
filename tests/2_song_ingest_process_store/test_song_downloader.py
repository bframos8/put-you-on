import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from queue import Queue

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "local" / "2_song_ingest_process_store"))

from song_downloader import SongDownloader, DOWNLOADS_DIR
from tools.datamodels import AlbumMetadata, AudioWithMetadata


@pytest.fixture
def mock_db_manager():
    """Create a mock DatabaseManager."""
    with patch('song_downloader.DatabaseManager') as MockDB:
        mock_instance = MagicMock()
        MockDB.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def output_queue():
    """Create an output queue for the downloader."""
    return Queue()


@pytest.fixture
def downloader(mock_db_manager, output_queue):
    """Create a SongDownloader instance with mocked dependencies."""
    return SongDownloader(output_queue)


class TestGetAlbumsToDownload:
    def test_get_albums_to_download(self, downloader, mock_db_manager):
        mock_db_manager.execute_query.return_value = [
            (1, "Album One", "Artist One", "http://example.com/album1"),
            (2, "Album Two", "Artist Two", "http://example.com/album2"),
        ]

        results = downloader._get_albums_to_download()

        assert len(results) == 2
        assert results[0] == (1, "Album One", "Artist One", "http://example.com/album1")
        mock_db_manager.execute_query.assert_called_once()
        assert "pending" in mock_db_manager.execute_query.call_args[0][0]

    def test_get_albums_to_download_empty(self, downloader, mock_db_manager):
        mock_db_manager.execute_query.return_value = []

        results = downloader._get_albums_to_download()

        assert results == []


class TestDownloadSongs:
    def test_download_songs_creates_directory(self, downloader, tmp_path):
        album_id = 123
        url = "http://example.com/album"

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('song_downloader.subprocess.run') as mock_run:
                downloader._download_songs(album_id, url)

        expected_dir = tmp_path / str(album_id)
        assert expected_dir.exists()

    def test_download_songs_calls_bandcamp_dl(self, downloader, tmp_path):
        album_id = 456
        url = "http://bandcamp.com/album"

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('song_downloader.subprocess.run') as mock_run:
                downloader._download_songs(album_id, url)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "bandcamp-dl"
        assert "--base-dir" in call_args
        assert url in call_args

    def test_download_songs_returns_audio_paths(self, downloader, tmp_path):
        album_id = 789
        url = "http://example.com/album"
        album_dir = tmp_path / str(album_id)
        album_dir.mkdir(parents=True)

        # Create fake audio files
        (album_dir / "track1.mp3").touch()
        (album_dir / "track2.flac").touch()
        (album_dir / "track3.wav").touch()

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('song_downloader.subprocess.run'):
                result = downloader._download_songs(album_id, url)

        assert len(result) == 3
        assert all(isinstance(p, Path) for p in result)

    def test_download_songs_filters_non_audio(self, downloader, tmp_path):
        album_id = 101
        url = "http://example.com/album"
        album_dir = tmp_path / str(album_id)
        album_dir.mkdir(parents=True)

        # Create mix of audio and non-audio files
        (album_dir / "track1.mp3").touch()
        (album_dir / "cover.jpg").touch()
        (album_dir / "info.txt").touch()
        (album_dir / "track2.flac").touch()

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('song_downloader.subprocess.run'):
                result = downloader._download_songs(album_id, url)

        assert len(result) == 2
        extensions = {p.suffix for p in result}
        assert extensions == {'.mp3', '.flac'}

    def test_download_songs_finds_nested_audio_files(self, downloader, tmp_path):
        album_id = 202
        url = "http://example.com/album"
        album_dir = tmp_path / str(album_id)
        nested_dir = album_dir / "Artist" / "Album"
        nested_dir.mkdir(parents=True)

        # Create nested audio files (bandcamp-dl creates nested structure)
        (nested_dir / "01 - Track One.mp3").touch()
        (nested_dir / "02 - Track Two.mp3").touch()

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('song_downloader.subprocess.run'):
                result = downloader._download_songs(album_id, url)

        assert len(result) == 2


class TestRun:
    def test_run_puts_items_in_queue(self, mock_db_manager, output_queue, tmp_path):
        mock_db_manager.execute_query.return_value = [
            (1, "Test Album", "Test Artist", "http://example.com/album"),
        ]

        # Create fake audio file
        album_dir = tmp_path / "1"
        album_dir.mkdir(parents=True)
        (album_dir / "track.mp3").touch()

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('song_downloader.subprocess.run'):
                downloader = SongDownloader(output_queue)
                downloader.run()

        # Should have one AudioWithMetadata item + None termination
        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        assert len(items) == 2
        assert isinstance(items[0], AudioWithMetadata)
        assert items[0].metadata.album_id == 1
        assert items[0].metadata.title == "Test Album"
        assert items[1] is None  # termination signal

    def test_run_sends_termination_signal(self, mock_db_manager, output_queue):
        mock_db_manager.execute_query.return_value = []

        with patch('song_downloader.subprocess.run'):
            downloader = SongDownloader(output_queue)
            downloader.run()

        # Even with no albums, should send termination signal
        assert output_queue.get() is None

    def test_run_handles_empty_album_list(self, mock_db_manager, output_queue):
        mock_db_manager.execute_query.return_value = []

        with patch('song_downloader.subprocess.run') as mock_run:
            downloader = SongDownloader(output_queue)
            downloader.run()

        # subprocess should never be called
        mock_run.assert_not_called()

    def test_run_processes_multiple_albums(self, mock_db_manager, output_queue, tmp_path):
        mock_db_manager.execute_query.return_value = [
            (1, "Album One", "Artist One", "http://example.com/album1"),
            (2, "Album Two", "Artist Two", "http://example.com/album2"),
        ]

        # Create fake audio files for both albums
        for album_id in [1, 2]:
            album_dir = tmp_path / str(album_id)
            album_dir.mkdir(parents=True)
            (album_dir / "track.mp3").touch()

        with patch('song_downloader.DOWNLOADS_DIR', tmp_path):
            with patch('song_downloader.subprocess.run'):
                downloader = SongDownloader(output_queue)
                downloader.run()

        items = []
        while not output_queue.empty():
            items.append(output_queue.get())

        # 2 audio items + 1 None
        assert len(items) == 3
        assert items[-1] is None
