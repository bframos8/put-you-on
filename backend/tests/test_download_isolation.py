"""A5: each _download gets its own temp dir under DOWNLOADS_DIR so concurrent
ingests can't grab each other's files, and the file-finding glob is scoped to
that temp dir (not the whole downloads dir). _cleanup removes the whole temp dir,
and a failed download cleans up after itself.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

import app.services.spotify_ingest_service as svc_mod
from app.services.spotify_ingest_service import SpotifyIngestService


@pytest.fixture
def svc(monkeypatch, tmp_path):
    # __init__ is no-op'd by the autouse patch_startup fixture (model not loaded,
    # DOWNLOADS_DIR not created), so point DOWNLOADS_DIR at a fresh tmp_path.
    monkeypatch.setattr(svc_mod, "DOWNLOADS_DIR", tmp_path)
    return SpotifyIngestService()


def _spotdl_writes(filename="Artist - Title.mp3"):
    """A subprocess.run side_effect that drops a fake audio file into whatever
    dir was passed via --output (mimicking a successful spotdl run)."""
    def _run(cmd, *args, **kwargs):
        out = Path(cmd[cmd.index("--output") + 1])
        (out / filename).write_bytes(b"fake-audio")
    return _run


def _spotdl_writes_nothing():
    def _run(cmd, *args, **kwargs):
        pass
    return _run


def test_download_returns_file_in_its_own_temp_dir(svc, tmp_path):
    with patch.object(svc_mod.subprocess, "run", side_effect=_spotdl_writes()):
        path = svc._download("http://fake/track")
    assert path.exists() and path.suffix == ".mp3"
    # Lives in a temp dir that is a direct child of DOWNLOADS_DIR, not the dir itself.
    assert path.parent.parent == tmp_path
    assert path.parent != tmp_path


def test_concurrent_downloads_get_distinct_dirs(svc):
    with patch.object(svc_mod.subprocess, "run", side_effect=_spotdl_writes()):
        a = svc._download("http://fake/a")
        b = svc._download("http://fake/b")
    assert a.parent != b.parent


def test_cleanup_removes_whole_temp_dir(svc):
    with patch.object(svc_mod.subprocess, "run", side_effect=_spotdl_writes()):
        path = svc._download("http://fake/track")
    temp_dir = path.parent
    assert temp_dir.is_dir()
    svc._cleanup(path)
    assert not temp_dir.exists()


def test_failed_download_raises_and_leaves_no_temp_dir(svc, tmp_path):
    with patch.object(svc_mod.subprocess, "run", side_effect=_spotdl_writes_nothing()):
        with pytest.raises(FileNotFoundError):
            svc._download("http://fake/track")
    # Self-clean: no leftover temp dir under DOWNLOADS_DIR.
    assert list(tmp_path.iterdir()) == []


def test_glob_is_scoped_to_temp_dir_not_downloads_dir(svc, tmp_path):
    # A stray audio file sitting directly in DOWNLOADS_DIR must not be returned.
    stray = tmp_path / "stray.mp3"
    stray.write_bytes(b"old")
    with patch.object(svc_mod.subprocess, "run", side_effect=_spotdl_writes("new.mp3")):
        path = svc._download("http://fake/track")
    assert path.name == "new.mp3"
    assert path != stray
    assert stray.exists()  # untouched by this download
