import json
from pathlib import Path

import numpy as np
from essentia.standard import TensorflowPredictEffnetDiscogs

from .genre_normalizer import normalize_genre

GRAPH_FILE = Path(__file__).resolve().parents[1] / "models" / "discogs-effnet-bs64-1.pb"
LABELS_FILE = Path(__file__).resolve().parents[1] / "models" / "discogs-effnet-bs64-1.json"
TOP_K = 5


class AudioGenreClassifier:
    def __init__(self) -> None:
        self.model = TensorflowPredictEffnetDiscogs(
            graphFilename=str(GRAPH_FILE), output="PartitionedCall:0"
        )
        with LABELS_FILE.open() as f:
            self.labels: list[str] = json.load(f)["classes"]

    def classify(self, audio: np.ndarray) -> str | None:
        """Predict a Bandcamp canonical genre from pre-loaded 16kHz mono audio.

        Returns the top-scoring prediction whose Discogs label normalizes to a
        canonical genre, walking the top-K labels until a mappable one is found.
        """
        frame_predictions = self.model(audio)
        if (
            not isinstance(frame_predictions, np.ndarray)
            or frame_predictions.ndim == 0
            or len(frame_predictions) == 0
        ):
            return None

        mean_probs = frame_predictions.mean(axis=0)
        top_indices = np.argsort(mean_probs)[::-1][:TOP_K]
        for idx in top_indices:
            canonical = normalize_genre([self.labels[int(idx)]])
            if canonical is not None:
                return canonical
        return None
