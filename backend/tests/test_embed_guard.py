"""
M1: the backend's SpotifyIngestService._embed mirrors the data_pipeline
SongEmbedder._embed_song empty-frame guard — it raises on degenerate audio
(model returns no frames) instead of producing a garbage mean. These tests
mirror data_pipeline/tests/song_pipeline/test_song_embedder.py::TestEmbedSong.

The service __init__ is no-op'd by the autouse patch_startup fixture, so we set
.model directly to a stub instead of loading Essentia/TF.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from app.services.spotify_ingest_service import SpotifyIngestService


def _service_with_model(return_value):
    svc = SpotifyIngestService()  # __init__ no-op'd by patch_startup
    svc.model = MagicMock(return_value=return_value)
    return svc


class TestEmbedGuard:
    def test_returns_mean_of_frames(self):
        frames = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        svc = _service_with_model(frames)

        result = svc._embed(np.zeros(16000))

        np.testing.assert_array_equal(result, np.array([2.5, 3.5, 4.5]))

    def test_raises_when_model_returns_empty_list(self):
        svc = _service_with_model([])

        with pytest.raises(ValueError, match="no frames"):
            svc._embed(np.zeros(8000))

    def test_raises_when_model_returns_non_empty_list(self):
        svc = _service_with_model([[1.0, 2.0], [3.0, 4.0]])

        with pytest.raises(ValueError, match="no frames"):
            svc._embed(np.zeros(8000))

    def test_raises_when_model_returns_empty_ndarray(self):
        svc = _service_with_model(np.array([]))

        with pytest.raises(ValueError, match="no frames"):
            svc._embed(np.zeros(8000))

    def test_raises_when_model_returns_scalar_ndarray(self):
        svc = _service_with_model(np.array(3.0))

        with pytest.raises(ValueError, match="no frames"):
            svc._embed(np.zeros(8000))
