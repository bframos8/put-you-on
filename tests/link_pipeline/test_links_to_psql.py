import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Import only the pure functions (not the __main__ block)
from data_pipeline.link_pipeline.links_to_psql import (
    load_progress,
    save_progress,
    DEFAULT_GENRE_URLS,
    PROGRESS_FILE,
)


class TestLoadProgress:
    def test_returns_defaults_when_no_file(self, tmp_path):
        missing_file = tmp_path / "genre_progress.json"

        with patch('data_pipeline.link_pipeline.links_to_psql.PROGRESS_FILE', missing_file):
            result = load_progress()

        assert result == DEFAULT_GENRE_URLS

    def test_loads_existing_progress_file(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        saved = {url: False for url in DEFAULT_GENRE_URLS}
        # Mark one as still needing processing
        first_url = list(DEFAULT_GENRE_URLS.keys())[0]
        saved[first_url] = True
        progress_file.write_text(json.dumps(saved))

        with patch('data_pipeline.link_pipeline.links_to_psql.PROGRESS_FILE', progress_file):
            result = load_progress()

        assert result == saved

    def test_resets_to_defaults_when_all_false(self, tmp_path):
        """If all genres are False (all done), reset so pipeline can re-run."""
        progress_file = tmp_path / "genre_progress.json"
        all_done = {url: False for url in DEFAULT_GENRE_URLS}
        progress_file.write_text(json.dumps(all_done))

        with patch('data_pipeline.link_pipeline.links_to_psql.PROGRESS_FILE', progress_file):
            result = load_progress()

        assert all(result.values())

    def test_preserves_partial_progress(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        urls = list(DEFAULT_GENRE_URLS.keys())
        partial = {url: (i % 2 == 0) for i, url in enumerate(urls)}  # Alternating True/False
        progress_file.write_text(json.dumps(partial))

        with patch('data_pipeline.link_pipeline.links_to_psql.PROGRESS_FILE', progress_file):
            result = load_progress()

        assert result == partial


class TestSaveProgress:
    def test_saves_progress_to_file(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        genre_urls = {"https://bandcamp.com/discover/rock/digital?s=new": False}

        with patch('data_pipeline.link_pipeline.links_to_psql.PROGRESS_FILE', progress_file):
            save_progress(genre_urls)

        assert progress_file.exists()
        saved = json.loads(progress_file.read_text())
        assert saved == genre_urls

    def test_save_and_load_roundtrip(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        original = {url: True for url in DEFAULT_GENRE_URLS}
        original[list(DEFAULT_GENRE_URLS.keys())[0]] = False

        with patch('data_pipeline.link_pipeline.links_to_psql.PROGRESS_FILE', progress_file):
            save_progress(original)
            loaded = load_progress()

        assert loaded == original

    def test_save_overwrites_existing_file(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        progress_file.write_text(json.dumps({"old": "data"}))

        new_data = {"https://bandcamp.com/discover/rock/digital?s=new": True}
        with patch('data_pipeline.link_pipeline.links_to_psql.PROGRESS_FILE', progress_file):
            save_progress(new_data)

        saved = json.loads(progress_file.read_text())
        assert saved == new_data
        assert "old" not in saved


class TestDefaultGenreUrls:
    def test_default_genre_urls_all_true(self):
        assert all(DEFAULT_GENRE_URLS.values())

    def test_default_genre_urls_contains_expected_genres(self):
        url_string = " ".join(DEFAULT_GENRE_URLS.keys())
        for genre in ["rock", "jazz", "hip-hop-rap", "electronic", "pop"]:
            assert genre in url_string

    def test_default_genre_urls_is_non_empty(self):
        assert len(DEFAULT_GENRE_URLS) > 0
