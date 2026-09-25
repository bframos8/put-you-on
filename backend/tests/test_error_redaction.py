"""
The Spotify client secret must never reach user_top_songs.ingest_error.

It did. `_download` ran spotdl with `check=True`, and `CalledProcessError` stringifies
the whole argv — including `--client-secret <value>`. `process_top_tracks` handed that
string to `_record_failure`, which stores the first 500 characters, and the secret sits
inside that window. Every failed download on the instance wrote the live credential into
the database and the container logs.

Two layers are tested here, because either alone is one refactor away from failing:
  - `_download` no longer produces an exception carrying the argv at all
  - `_record_failure` redacts known secret values whatever the producer did
"""
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import UserTopSong
from app.services.spotify_ingest_service import _redact_secrets

SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]  # set by conftest before any app import


def make_service():
    with patch(
        "app.services.spotify_ingest_service.SpotifyIngestService.__init__",
        return_value=None,
    ):
        from app.services.spotify_ingest_service import SpotifyIngestService
        return SpotifyIngestService()


class TestRedactSecrets:
    def test_removes_the_client_secret(self):
        assert SECRET not in _redact_secrets(f"boom --client-secret {SECRET} bang")

    def test_leaves_ordinary_text_alone(self):
        assert _redact_secrets("spotdl exited 1: KeyError") == "spotdl exited 1: KeyError"

    def test_is_safe_when_the_variable_is_unset(self, monkeypatch):
        monkeypatch.delenv("INGEST_WORKER_TOKEN", raising=False)
        assert _redact_secrets("nothing to redact") == "nothing to redact"

    def test_redacts_the_worker_token_too(self, monkeypatch):
        # The worker (10.6) POSTs error strings from another machine; its token is the
        # other value that could plausibly end up in one.
        monkeypatch.setenv("INGEST_WORKER_TOKEN", "tok-abc-123")
        assert "tok-abc-123" not in _redact_secrets("failed with tok-abc-123")


class TestRecordFailureRedacts:
    def test_secret_never_reaches_the_column(self):
        svc = make_service()
        row = MagicMock(spec=UserTopSong)
        row.ingest_attempts = 0
        row.ingest_failed_at = None
        row.track_title = "A Song"

        svc._record_failure(
            row, RuntimeError(f"Command '[spotdl, --client-secret, {SECRET}]' failed"),
            MagicMock(),
        )
        assert SECRET not in row.ingest_error


class TestDownloadDoesNotLeakArgv:
    def _run_download(self, returncode, stderr):
        svc = make_service()
        completed = subprocess.CompletedProcess(
            args=["spotdl", "--client-secret", SECRET], returncode=returncode,
            stdout="", stderr=stderr,
        )
        with patch("app.services.spotify_ingest_service.subprocess.run", return_value=completed):
            return svc._download("https://open.spotify.com/track/abc")

    def test_failure_message_has_neither_the_secret_nor_the_argv(self):
        with pytest.raises(Exception) as exc:
            self._run_download(1, "ERROR: [youtube] Sign in to confirm you're not a bot.")
        message = str(exc.value)
        assert SECRET not in message
        assert "--client-secret" not in message

    def test_failure_message_still_says_what_went_wrong(self):
        # Redaction is worthless if it also removes the reason. This string is what shows
        # up in triage.
        with pytest.raises(Exception) as exc:
            self._run_download(1, "ERROR: [youtube] Sign in to confirm you're not a bot.")
        assert "not a bot" in str(exc.value)

    def test_check_true_is_not_used(self):
        """`check=True` is what reintroduces the leak, so pin it directly.

        Without this, someone tidying the call back to `check=True` restores the bug and
        every other test here still passes, because the argv would be inside
        CalledProcessError rather than in our own message.
        """
        svc = make_service()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch(
            "app.services.spotify_ingest_service.subprocess.run", return_value=completed
        ) as mock_run:
            with pytest.raises(FileNotFoundError):  # no audio produced by the mock
                svc._download("https://open.spotify.com/track/abc")
        assert mock_run.call_args.kwargs.get("check") is not True
