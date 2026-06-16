"""
Tests for /api/v1/items/top_tracks/ endpoint.

Reads UserTopSong rows for the authenticated user. Query chain used:
    db.query(UserTopSong).filter(...).order_by(...).limit(...).all()

The shared mock_db fixture wires .first() to the authenticated user for
get_current_user; each test here additionally stubs the .all() terminal.
"""

from unittest.mock import MagicMock

from app.db.models import UserTopSong

TOP_TRACKS_URL = "/api/v1/items/top_tracks/"


def _make_top_song(
    *,
    id: int,
    spotify_track_id: str = "spot_abc",
    track_title: str | None = "Track Title",
    artist_name: str | None = "Artist Name",
    album_title: str | None = "Album Title",
    image_url: str | None = "https://img.example.com/a.jpg",
    spotify_url: str | None = "https://open.spotify.com/track/abc",
    duration_ms: int | None = None,
) -> MagicMock:
    row = MagicMock(spec=UserTopSong)
    row.id = id
    row.spotify_track_id = spotify_track_id
    row.track_title = track_title
    row.artist_name = artist_name
    row.album_title = album_title
    row.image_url = image_url
    row.spotify_url = spotify_url
    # Set explicitly: with spec=UserTopSong, an un-set real column attribute
    # returns an auto-child MagicMock that fails Pydantic's int | None.
    row.duration_ms = duration_ms
    return row


def _stub_rows(mock_db, rows: list) -> None:
    """Configure the .filter().order_by().limit().all() chain."""
    (
        mock_db.query.return_value
        .filter.return_value
        .order_by.return_value
        .limit.return_value
        .all.return_value
    ) = rows


# ══════════════════════════════════════════════════════════════════════════════
# Auth gate
# ══════════════════════════════════════════════════════════════════════════════

class TestTopTracksAuthGate:
    def test_no_cookie_returns_401(self, client):
        resp = client.get(TOP_TRACKS_URL)
        assert resp.status_code == 401

    def test_garbage_cookie_returns_401(self, client):
        resp = client.get(TOP_TRACKS_URL, cookies={"session": "garbage.value.here"})
        assert resp.status_code == 401

    def test_session_for_deleted_user_returns_401(self, client, valid_session, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Happy path
# ══════════════════════════════════════════════════════════════════════════════

class TestTopTracksHappyPath:
    def test_returns_200(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [])
        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        assert resp.status_code == 200

    def test_empty_snapshot_returns_empty_tracks_list(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [])
        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        assert resp.json() == {"tracks": []}

    def test_response_has_tracks_key(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [_make_top_song(id=1)])
        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        assert "tracks" in resp.json()
        assert isinstance(resp.json()["tracks"], list)

    def test_track_items_have_expected_schema(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [_make_top_song(id=1)])
        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        track = resp.json()["tracks"][0]
        assert set(track.keys()) == {
            "id",
            "title",
            "artist_name",
            "album_title",
            "image_url",
            "album_url",
            "duration_ms",
            "popularity",
        }

    def test_field_mapping_from_user_top_song(self, client, valid_session, mock_db):
        row = _make_top_song(
            id=1,
            spotify_track_id="spot_xyz",
            track_title="Silk Chiffon",
            artist_name="MUNA",
            album_title="Silk Chiffon",
            image_url="https://img.example.com/silk.jpg",
            spotify_url="https://open.spotify.com/track/silkchiffon",
        )
        _stub_rows(mock_db, [row])

        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        track = resp.json()["tracks"][0]
        assert track["id"] == "spot_xyz"
        assert track["title"] == "Silk Chiffon"
        assert track["artist_name"] == "MUNA"
        assert track["album_title"] == "Silk Chiffon"
        assert track["image_url"] == "https://img.example.com/silk.jpg"
        assert track["album_url"] == "https://open.spotify.com/track/silkchiffon"

    def test_duration_ms_and_popularity_are_null(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [_make_top_song(id=1)])
        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        track = resp.json()["tracks"][0]
        assert track["duration_ms"] is None
        assert track["popularity"] is None

    def test_duration_ms_flows_through_when_present(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [_make_top_song(id=1, duration_ms=214000)])
        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        track = resp.json()["tracks"][0]
        assert track["duration_ms"] == 214000

    def test_multiple_tracks_returned_in_order(self, client, valid_session, mock_db):
        rows = [
            _make_top_song(id=i, spotify_track_id=f"spot_{i}", track_title=f"Track {i}")
            for i in range(1, 6)
        ]
        _stub_rows(mock_db, rows)

        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        tracks = resp.json()["tracks"]
        assert [t["id"] for t in tracks] == ["spot_1", "spot_2", "spot_3", "spot_4", "spot_5"]


# ══════════════════════════════════════════════════════════════════════════════
# Query construction — filter/order/limit reach SQLAlchemy correctly
# ══════════════════════════════════════════════════════════════════════════════

class TestTopTracksQuery:
    def test_queries_user_top_song_model(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [])
        client.get(TOP_TRACKS_URL, cookies={"session": valid_session})

        queried_models = [call.args[0] for call in mock_db.query.call_args_list]
        assert UserTopSong in queried_models

    def test_applies_limit_of_10(self, client, valid_session, mock_db):
        _stub_rows(mock_db, [])
        client.get(TOP_TRACKS_URL, cookies={"session": valid_session})

        limit_mock = (
            mock_db.query.return_value
            .filter.return_value
            .order_by.return_value
            .limit
        )
        limit_mock.assert_called_with(10)


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestTopTracksEdgeCases:
    def test_nullable_fields_serialize_as_null(self, client, valid_session, mock_db):
        row = _make_top_song(
            id=1,
            track_title=None,
            artist_name=None,
            album_title=None,
            image_url=None,
            spotify_url=None,
        )
        _stub_rows(mock_db, [row])

        resp = client.get(TOP_TRACKS_URL, cookies={"session": valid_session})
        track = resp.json()["tracks"][0]
        assert track["title"] is None
        assert track["artist_name"] is None
        assert track["album_title"] is None
        assert track["image_url"] is None
        assert track["album_url"] is None
