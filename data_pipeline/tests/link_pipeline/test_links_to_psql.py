import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from data_pipeline.link_pipeline.runner import (
    load_progress,
    save_progress,
    run_pipeline,
    DEFAULT_GENRE_URLS,
    PROGRESS_FILE,
)


class TestLoadProgress:
    def test_returns_defaults_when_no_file(self, tmp_path):
        missing_file = tmp_path / "genre_progress.json"

        with patch('data_pipeline.link_pipeline.runner.PROGRESS_FILE', missing_file):
            result = load_progress()

        assert result == DEFAULT_GENRE_URLS

    def test_loads_existing_progress_file(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        saved = {url: False for url in DEFAULT_GENRE_URLS}
        # Mark one as still needing processing
        first_url = list(DEFAULT_GENRE_URLS.keys())[0]
        saved[first_url] = True
        progress_file.write_text(json.dumps(saved))

        with patch('data_pipeline.link_pipeline.runner.PROGRESS_FILE', progress_file):
            result = load_progress()

        assert result == saved

    def test_resets_to_defaults_when_all_false(self, tmp_path):
        """If all genres are False (all done), reset so pipeline can re-run."""
        progress_file = tmp_path / "genre_progress.json"
        all_done = {url: False for url in DEFAULT_GENRE_URLS}
        progress_file.write_text(json.dumps(all_done))

        with patch('data_pipeline.link_pipeline.runner.PROGRESS_FILE', progress_file):
            result = load_progress()

        assert all(result.values())

    def test_preserves_partial_progress(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        urls = list(DEFAULT_GENRE_URLS.keys())
        partial = {url: (i % 2 == 0) for i, url in enumerate(urls)}  # Alternating True/False
        progress_file.write_text(json.dumps(partial))

        with patch('data_pipeline.link_pipeline.runner.PROGRESS_FILE', progress_file):
            result = load_progress()

        assert result == partial


class TestSaveProgress:
    def test_saves_progress_to_file(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        genre_urls = {"https://bandcamp.com/discover/rock/digital?s=new": False}

        with patch('data_pipeline.link_pipeline.runner.PROGRESS_FILE', progress_file):
            save_progress(genre_urls)

        assert progress_file.exists()
        saved = json.loads(progress_file.read_text())
        assert saved == genre_urls

    def test_save_and_load_roundtrip(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        original = {url: True for url in DEFAULT_GENRE_URLS}
        original[list(DEFAULT_GENRE_URLS.keys())[0]] = False

        with patch('data_pipeline.link_pipeline.runner.PROGRESS_FILE', progress_file):
            save_progress(original)
            loaded = load_progress()

        assert loaded == original

    def test_save_overwrites_existing_file(self, tmp_path):
        progress_file = tmp_path / "genre_progress.json"
        progress_file.write_text(json.dumps({"old": "data"}))

        new_data = {"https://bandcamp.com/discover/rock/digital?s=new": True}
        with patch('data_pipeline.link_pipeline.runner.PROGRESS_FILE', progress_file):
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


SAMPLE_ITEM = {
    "item_id": 1001,
    "band_id": 2001,
    "band_name": "Test Band",
    "band_url": "https://testband.bandcamp.com",
    "band_location": "NYC",
    "title": "Test Album",
    "item_duration": 3600,
    "release_date": "2024-01-01",
    "item_url": "https://testband.bandcamp.com/album/test",
    "primary_image": {"image_id": 999},
}


def _make_mock_db(artist_id=42, existing_albums=None):
    """Return a mock DatabaseManager pre-configured for the batch pipeline."""
    mock_db = MagicMock()
    mock_db.fetch_existing_values.return_value = existing_albums or set()
    mock_db.fetch_id_map.return_value = {SAMPLE_ITEM["band_id"]: artist_id}
    return mock_db


def _album_insert_call(mock_db):
    """Return the insert_rows_ignore_conflicts call args for the albums table."""
    calls = mock_db.insert_rows_ignore_conflicts.call_args_list
    album_calls = [c for c in calls if c.args[0] == "albums"]
    assert album_calls, "No insert_rows_ignore_conflicts call found for 'albums'"
    return album_calls[0]


def _run_pipeline_for_genre(genre, items, mock_db=None):
    if mock_db is None:
        mock_db = _make_mock_db()
    genre_urls = {f"https://bandcamp.com/discover/{genre}/digital?s=new": True}

    with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
         patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
         patch('data_pipeline.link_pipeline.runner.save_progress'):
        MockCrawler.return_value.get_discover_payloads.return_value = items
        run_pipeline(mock_db)

    return mock_db


class TestAlbumBatchInsertGenre:
    def test_album_insert_includes_genre_column(self):
        mock_db = _run_pipeline_for_genre("jazz", [SAMPLE_ITEM])
        column_names = _album_insert_call(mock_db).args[1]
        assert "genre" in column_names

    def test_album_insert_genre_value_matches_url(self):
        mock_db = _run_pipeline_for_genre("jazz", [SAMPLE_ITEM])
        call_args = _album_insert_call(mock_db)
        column_names = call_args.args[1]
        rows = call_args.args[2]
        genre_idx = column_names.index("genre")
        assert rows[0][genre_idx] == "jazz"

    @pytest.mark.parametrize("genre", ["electronic", "hip-hop-rap", "ambient"])
    def test_genre_extracted_correctly_from_url(self, genre):
        item = {**SAMPLE_ITEM, "item_id": hash(genre)}
        mock_db = _make_mock_db()
        mock_db = _run_pipeline_for_genre(genre, [item], mock_db)
        call_args = _album_insert_call(mock_db)
        column_names = call_args.args[1]
        rows = call_args.args[2]
        genre_idx = column_names.index("genre")
        assert rows[0][genre_idx] == genre


class TestBatchInsertBehavior:
    def test_multiple_albums_sent_in_one_batch_call(self):
        """All albums for a genre should go in a single insert call, not per-row."""
        items = [
            {**SAMPLE_ITEM, "item_id": 1001 + i, "band_id": 2001}
            for i in range(5)
        ]
        mock_db = _run_pipeline_for_genre("rock", items)
        album_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "albums"
        ]
        assert len(album_calls) == 1
        rows = album_calls[0].args[2]
        assert len(rows) == 5

    def test_unique_artists_batched_in_one_call(self):
        """Distinct artists across items should be inserted in one batch."""
        items = [
            {**SAMPLE_ITEM, "item_id": 1001 + i, "band_id": 2001 + i, "band_name": f"Band {i}"}
            for i in range(3)
        ]
        mock_db = _make_mock_db()
        mock_db.fetch_id_map.return_value = {2001 + i: 42 + i for i in range(3)}
        _run_pipeline_for_genre("rock", items, mock_db)

        artist_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "artists"
        ]
        assert len(artist_calls) == 1
        assert len(artist_calls[0].args[2]) == 3

    def test_duplicate_artist_across_items_inserted_once(self):
        """Same artist on multiple albums should only appear once in the artist batch."""
        items = [
            {**SAMPLE_ITEM, "item_id": 1001 + i, "band_id": 2001}  # same band_id
            for i in range(3)
        ]
        mock_db = _run_pipeline_for_genre("rock", items)
        artist_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "artists"
        ]
        assert len(artist_calls) == 1
        assert len(artist_calls[0].args[2]) == 1

    def test_no_individual_upsert_row_calls(self):
        """The old single-row upsert methods should not be called."""
        items = [{**SAMPLE_ITEM, "item_id": 1001 + i} for i in range(3)]
        mock_db = _run_pipeline_for_genre("rock", items)
        mock_db.upsert_row.assert_not_called()
        mock_db.upsert_row_and_return_id.assert_not_called()


class TestSkipsExistingAlbums:
    def test_albums_in_db_are_not_reinserted(self):
        """Albums already in the DB should be filtered before insert."""
        existing = {SAMPLE_ITEM["item_id"]}
        mock_db = _make_mock_db(existing_albums=existing)
        _run_pipeline_for_genre("rock", [SAMPLE_ITEM], mock_db)

        album_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "albums"
        ]
        assert len(album_calls) == 0

    def test_fetch_existing_values_called_with_candidate_ids(self):
        """fetch_existing_values should be called with the album IDs from the payload."""
        mock_db = _run_pipeline_for_genre("rock", [SAMPLE_ITEM])
        mock_db.fetch_existing_values.assert_called_once_with(
            "albums", "external_source_id", [SAMPLE_ITEM["item_id"]]
        )

    def test_only_new_albums_inserted_when_some_exist(self):
        """Only albums not already in DB should be inserted."""
        items = [
            {**SAMPLE_ITEM, "item_id": 1001},
            {**SAMPLE_ITEM, "item_id": 1002},
            {**SAMPLE_ITEM, "item_id": 1003},
        ]
        existing = {1001, 1003}  # Two already in DB
        mock_db = _make_mock_db(existing_albums=existing)
        _run_pipeline_for_genre("rock", items, mock_db)

        album_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "albums"
        ]
        assert len(album_calls) == 1
        rows = album_calls[0].args[2]
        assert len(rows) == 1
        # The inserted row should be for item_id 1002
        external_source_id_idx = album_calls[0].args[1].index("external_source_id")
        assert rows[0][external_source_id_idx] == 1002

    def test_in_run_cache_skips_duplicate_album_ids(self):
        """Albums seen earlier in the same run (same genre crawl) should be skipped."""
        # Two items with the same item_id
        item_a = {**SAMPLE_ITEM, "item_id": 1001}
        item_b = {**SAMPLE_ITEM, "item_id": 1001, "title": "Duplicate"}
        mock_db = _run_pipeline_for_genre("rock", [item_a, item_b])

        album_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "albums"
        ]
        rows = album_calls[0].args[2]
        assert len(rows) == 1


class TestArtistIdPassedToAlbum:
    def test_artist_id_from_fetch_id_map_used_in_album_row(self):
        """The artist DB id returned by fetch_id_map should appear in the album row."""
        mock_db = _make_mock_db(artist_id=99)
        mock_db.fetch_id_map.return_value = {SAMPLE_ITEM["band_id"]: 99}
        _run_pipeline_for_genre("jazz", [SAMPLE_ITEM], mock_db)

        call_args = _album_insert_call(mock_db)
        column_names = call_args.args[1]
        rows = call_args.args[2]
        artist_id_idx = column_names.index("artist_id")
        assert rows[0][artist_id_idx] == 99

    def test_cached_artist_not_reinserted_for_second_genre(self):
        """An artist seen in genre 1 should not trigger another DB insert in genre 2."""
        item1 = {**SAMPLE_ITEM, "item_id": 1001}
        item2 = {**SAMPLE_ITEM, "item_id": 1002}  # same band_id

        mock_db = _make_mock_db()
        genre_urls = {
            "https://bandcamp.com/discover/rock/digital?s=new": True,
            "https://bandcamp.com/discover/jazz/digital?s=new": True,
        }

        with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
             patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
             patch('data_pipeline.link_pipeline.runner.save_progress'):
            MockCrawler.return_value.get_discover_payloads.side_effect = [[item1], [item2]]
            run_pipeline(mock_db)

        artist_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "artists"
        ]
        # Artist should only be inserted once (during rock), not again for jazz
        assert len(artist_calls) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEmptyPayload:
    def test_no_db_calls_when_payload_empty(self):
        """Empty crawler payload should not trigger any insert or fetch calls."""
        mock_db = _make_mock_db()
        _run_pipeline_for_genre("rock", [], mock_db)

        mock_db.insert_rows_ignore_conflicts.assert_not_called()
        mock_db.fetch_id_map.assert_not_called()

    def test_fetch_existing_values_called_with_empty_list_on_empty_payload(self):
        """fetch_existing_values is still called but with an empty list (returns early)."""
        mock_db = _make_mock_db()
        _run_pipeline_for_genre("rock", [], mock_db)

        mock_db.fetch_existing_values.assert_called_once_with(
            "albums", "external_source_id", []
        )

    def test_progress_still_saved_when_payload_empty(self):
        """Genre should be marked done even if there was nothing to insert."""
        mock_db = _make_mock_db()
        genre_url = "https://bandcamp.com/discover/rock/digital?s=new"
        genre_urls = {genre_url: True}

        with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
             patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
             patch('data_pipeline.link_pipeline.runner.save_progress') as mock_save:
            MockCrawler.return_value.get_discover_payloads.return_value = []
            run_pipeline(mock_db)

        mock_save.assert_called_once()
        saved_state = mock_save.call_args.args[0]
        assert saved_state[genre_url] is False


class TestAllAlbumsFiltered:
    def test_all_in_run_cache_skips_all_db_inserts(self):
        """If all items are already in the run-level cache, no inserts happen."""
        # Pre-populate by running genre 1, then re-run same items as genre 2
        item = {**SAMPLE_ITEM, "item_id": 1001}
        mock_db = _make_mock_db()
        genre_urls = {
            "https://bandcamp.com/discover/rock/digital?s=new": True,
            "https://bandcamp.com/discover/jazz/digital?s=new": True,
        }

        with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
             patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
             patch('data_pipeline.link_pipeline.runner.save_progress'):
            # Both genres return the same item
            MockCrawler.return_value.get_discover_payloads.side_effect = [[item], [item]]
            run_pipeline(mock_db)

        album_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "albums"
        ]
        # Album should only be inserted once (rock), not again for jazz
        assert len(album_calls) == 1

    def test_all_in_db_skips_inserts(self):
        """If every candidate ID already exists in the DB, nothing is inserted."""
        mock_db = _make_mock_db(existing_albums={SAMPLE_ITEM["item_id"]})
        _run_pipeline_for_genre("rock", [SAMPLE_ITEM], mock_db)

        mock_db.insert_rows_ignore_conflicts.assert_not_called()
        mock_db.fetch_id_map.assert_not_called()


class TestUrlStripping:
    def test_album_url_query_params_stripped(self):
        item = {**SAMPLE_ITEM, "item_url": "https://testband.bandcamp.com/album/test?from=discover&lang=en"}
        mock_db = _run_pipeline_for_genre("rock", [item])

        call_args = _album_insert_call(mock_db)
        col = call_args.args[1]
        rows = call_args.args[2]
        url_idx = col.index("url")
        assert rows[0][url_idx] == "https://testband.bandcamp.com/album/test"
        assert "?" not in rows[0][url_idx]

    def test_artist_url_query_params_stripped(self):
        item = {**SAMPLE_ITEM, "band_url": "https://testband.bandcamp.com?from=discover"}
        mock_db = _run_pipeline_for_genre("rock", [item])

        artist_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "artists"
        ]
        url_idx = artist_calls[0].args[1].index("url")
        assert artist_calls[0].args[2][0][url_idx] == "https://testband.bandcamp.com"

    def test_album_url_without_query_string_unchanged(self):
        item = {**SAMPLE_ITEM, "item_url": "https://testband.bandcamp.com/album/test"}
        mock_db = _run_pipeline_for_genre("rock", [item])

        call_args = _album_insert_call(mock_db)
        col = call_args.args[1]
        rows = call_args.args[2]
        url_idx = col.index("url")
        assert rows[0][url_idx] == "https://testband.bandcamp.com/album/test"


class TestAlbumRowFields:
    def _get_row_field(self, mock_db, field_name):
        call_args = _album_insert_call(mock_db)
        col = call_args.args[1]
        rows = call_args.args[2]
        return rows[0][col.index(field_name)]

    def test_source_is_always_bandcamp(self):
        mock_db = _run_pipeline_for_genre("rock", [SAMPLE_ITEM])
        assert self._get_row_field(mock_db, "source") == "bandcamp"

    def test_work_status_is_always_pending(self):
        mock_db = _run_pipeline_for_genre("rock", [SAMPLE_ITEM])
        assert self._get_row_field(mock_db, "work_status") == "pending"

    def test_image_url_constructed_from_image_id(self):
        item = {**SAMPLE_ITEM, "primary_image": {"image_id": 12345}}
        mock_db = _run_pipeline_for_genre("rock", [item])
        expected = "https://f4.bcbits.com/img/a12345_0.jpg"
        assert self._get_row_field(mock_db, "image_url") == expected

    def test_external_source_id_is_item_id(self):
        item = {**SAMPLE_ITEM, "item_id": 9999}
        mock_db = _make_mock_db()
        mock_db.fetch_id_map.return_value = {item["band_id"]: 42}
        _run_pipeline_for_genre("rock", [item], mock_db)
        assert self._get_row_field(mock_db, "external_source_id") == 9999

    def test_artist_name_denormalized_into_album_row(self):
        item = {**SAMPLE_ITEM, "band_name": "Specific Artist Name"}
        mock_db = _run_pipeline_for_genre("rock", [item])
        assert self._get_row_field(mock_db, "artist_name") == "Specific Artist Name"

    def test_all_expected_columns_present(self):
        mock_db = _run_pipeline_for_genre("rock", [SAMPLE_ITEM])
        call_args = _album_insert_call(mock_db)
        column_names = call_args.args[1]
        expected = {
            "title", "external_source_id", "source", "url", "duration",
            "release_date", "artist_name", "artist_id", "work_status", "image_url", "genre",
        }
        assert set(column_names) == expected


class TestProgressTracking:
    def _run_two_genres(self, payloads):
        mock_db = _make_mock_db()
        rock_url = "https://bandcamp.com/discover/rock/digital?s=new"
        jazz_url = "https://bandcamp.com/discover/jazz/digital?s=new"
        genre_urls = {rock_url: True, jazz_url: True}
        saved_states = []

        def capture_save(state):
            saved_states.append({k: v for k, v in state.items()})

        with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
             patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
             patch('data_pipeline.link_pipeline.runner.save_progress', side_effect=capture_save):
            MockCrawler.return_value.get_discover_payloads.side_effect = payloads
            run_pipeline(mock_db)

        return saved_states, rock_url, jazz_url

    def test_save_progress_called_once_per_genre(self):
        saved_states, _, _ = self._run_two_genres([[], []])
        assert len(saved_states) == 2

    def test_genre_marked_false_after_processing(self):
        saved_states, rock_url, jazz_url = self._run_two_genres([[], []])
        # After rock finishes, rock=False, jazz still True
        assert saved_states[0][rock_url] is False
        assert saved_states[0][jazz_url] is True
        # After jazz finishes, both False
        assert saved_states[1][jazz_url] is False

    def test_skipped_genre_not_crawled(self):
        """Genres with should_process=False should never have their crawler invoked."""
        mock_db = _make_mock_db()
        genre_urls = {
            "https://bandcamp.com/discover/rock/digital?s=new": False,
            "https://bandcamp.com/discover/jazz/digital?s=new": True,
        }

        with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
             patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
             patch('data_pipeline.link_pipeline.runner.save_progress'):
            MockCrawler.return_value.get_discover_payloads.return_value = []
            run_pipeline(mock_db)

        # Crawler.run() should only be called once (for jazz)
        assert MockCrawler.return_value.run.call_count == 1


class TestArtistCacheEdgeCases:
    def test_fetch_id_map_not_called_when_all_artists_cached(self):
        """If all artists are already in the run cache, fetch_id_map is never called."""
        item1 = {**SAMPLE_ITEM, "item_id": 1001}
        item2 = {**SAMPLE_ITEM, "item_id": 1002}

        mock_db = _make_mock_db()
        genre_urls = {
            "https://bandcamp.com/discover/rock/digital?s=new": True,
            "https://bandcamp.com/discover/jazz/digital?s=new": True,
        }

        with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
             patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
             patch('data_pipeline.link_pipeline.runner.save_progress'):
            MockCrawler.return_value.get_discover_payloads.side_effect = [[item1], [item2]]
            run_pipeline(mock_db)

        # fetch_id_map should only be called once (when artist first seen in rock)
        assert mock_db.fetch_id_map.call_count == 1

    def test_fetch_id_map_called_with_only_uncached_band_ids(self):
        """fetch_id_map should only receive band IDs not already in the artist cache."""
        band_a = {**SAMPLE_ITEM, "item_id": 1001, "band_id": 2001}
        band_b = {**SAMPLE_ITEM, "item_id": 1002, "band_id": 2002, "band_name": "Band B"}

        mock_db = _make_mock_db()
        mock_db.fetch_id_map.return_value = {2001: 10, 2002: 20}

        _run_pipeline_for_genre("rock", [band_a, band_b], mock_db)

        fetch_call = mock_db.fetch_id_map.call_args
        queried_band_ids = set(fetch_call.args[2])
        assert queried_band_ids == {2001, 2002}

    def test_artist_insert_not_called_when_all_artists_already_cached(self):
        """Second genre with the same artist should produce zero artist inserts."""
        item1 = {**SAMPLE_ITEM, "item_id": 1001}
        item2 = {**SAMPLE_ITEM, "item_id": 1002}

        mock_db = _make_mock_db()
        genre_urls = {
            "https://bandcamp.com/discover/rock/digital?s=new": True,
            "https://bandcamp.com/discover/jazz/digital?s=new": True,
        }

        with patch('data_pipeline.link_pipeline.runner.BandcampCrawler') as MockCrawler, \
             patch('data_pipeline.link_pipeline.runner.load_progress', return_value=genre_urls), \
             patch('data_pipeline.link_pipeline.runner.save_progress'):
            MockCrawler.return_value.get_discover_payloads.side_effect = [[item1], [item2]]
            run_pipeline(mock_db)

        artist_calls = [
            c for c in mock_db.insert_rows_ignore_conflicts.call_args_list
            if c.args[0] == "artists"
        ]
        assert len(artist_calls) == 1  # Only from rock, not jazz
