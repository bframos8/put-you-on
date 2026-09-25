"""Download, load and embed one track (gameplan 10.6).

**These three helpers mirror `SpotifyIngestService._download`, `._load_audio` and
`._embed` in the backend, and they must stay in sync.** They are duplicated rather than
imported because importing them would drag in FastAPI, SQLAlchemy and the whole app; the
same "keep in sync by convention" arrangement already exists between the backend and
`data_pipeline`'s SongEmbedder. If you change the sample rate, the resample quality, the
model output or the frame-mean here, change it in
`backend/app/services/spotify_ingest_service.py` too — an embedding computed differently
from the corpus lands in a different space, and nothing downstream would notice. It
would just quietly return bad recommendations.

The genre classifier is NOT duplicated: it is imported from the backend package, which
needs nothing heavier than numpy and essentia. See run.py.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import essentia
import numpy as np
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

essentia.log.warningActive = False

logger = logging.getLogger(__name__)

# The worker's own scratch directory, deliberately not the backend's
# app/services/downloads/: this process may well be running from the same checkout, and
# two writers in one temp tree is a problem nobody needs.
DOWNLOADS_DIR = Path(__file__).resolve().parent / "downloads"

# One copy of the model, shared with the backend image rather than committed a third
# time. The repo already carries it twice (backend/app/models and data_pipeline/models);
# the audit note about that is in the gameplan's deferred list.
GRAPH_FILE = (
    Path(__file__).resolve().parents[1]
    / "backend" / "app" / "models" / "discogs-effnet-bs64-1.pb"
)

AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg"}


class Embedder:
    """Wraps the effnet graph's embedding output.

    Kept as a class so the model loads once at startup rather than per track — it is
    ~18 MB of graph and a few hundred MB of runtime, and a per-track load would dominate
    the job. Note this reads `PartitionedCall:1` (embeddings) while AudioGenreClassifier
    reads `PartitionedCall:0` (labels) off the same file, so the worker holds two
    instances. That is the same arrangement the backend has, and the second one costs
    about 36 MB.
    """

    def __init__(self) -> None:
        self.model = TensorflowPredictEffnetDiscogs(
            graphFilename=str(GRAPH_FILE), output="PartitionedCall:1"
        )

    def embed(self, audio: np.ndarray) -> list[float]:
        # Mirrors SpotifyIngestService._embed, including the degenerate-audio guard:
        # raise rather than return a garbage mean over zero frames.
        frame_embeddings = self.model(audio)
        if (
            not isinstance(frame_embeddings, np.ndarray)
            or frame_embeddings.ndim == 0
            or len(frame_embeddings) == 0
        ):
            raise ValueError(
                f"Model returned no frames — audio may be too short "
                f"({len(audio) / 16000:.2f}s)"
            )
        return frame_embeddings.mean(axis=0).tolist()


def download(spotify_url: str, client_id: str, client_secret: str, js_runtime: str = "node") -> Path:
    """Fetch one track's audio with spotdl. Mirrors SpotifyIngestService._download,
    plus two flags the backend does not pass. Both were found by measurement on
    2026-09-25 and both are required for this to work at all:

    **`--audio youtube`.** Not a preference — it is how you get past spotdl's own
    pre-flight check. spotdl 4.5.2 tests for a YouTube Music block by searching for the
    single letter `"a"` *unfiltered* and counting usable results. Today that query
    returns exactly one album, which has no `videoId`, so spotdl's own filter drops it,
    the count is zero, and it aborts the whole run with "You are blocked by YouTube
    Music. Please use a VPN". The message is wrong: a real search (`filter="songs"`)
    returns 20 usable results from the same machine, seconds apart. The check only runs
    when `youtube-music` is among the providers, so naming a different one skips it.

    **`--yt-dlp-args "--js-runtimes <runtime>"`.** Current yt-dlp needs a JavaScript
    runtime for YouTube and only enables Deno by default. Without one, extraction falls
    back to a client whose formats have no URLs and the download dies on "Requested
    format is not available" — or, worse, picks a format that then 403s. Node is what a
    machine with a JS toolchain already has; set WORKER_JS_RUNTIME to use another.

    That combination downloads successfully from a residential connection, which is the
    whole premise of 10.6. On the EC2 instance the same request is answered with "Sign
    in to confirm you're not a bot" and has been since before that box was built (10.3).
    """
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    # Each download gets its own temp dir so concurrent jobs can't pick up each other's
    # files, and so an empty result unambiguously means "produced no audio".
    job_dir = Path(tempfile.mkdtemp(prefix="ingest_", dir=DOWNLOADS_DIR))
    try:
        result = subprocess.run(
            ["spotdl", "--no-cache", "--audio", "youtube",
             "--format", "mp3", "--bitrate", "320k",
             "--yt-dlp-args", f"--js-runtimes {js_runtime}",
             "--client-id", client_id,
             "--client-secret", client_secret,
             "--output", str(job_dir),
             spotify_url],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Deliberately NOT `check=True`. CalledProcessError stringifies the whole
            # argv, which contains --client-secret, and this string travels to the app
            # and is stored in user_top_songs.ingest_error. A download failure must not
            # put the Spotify client secret in the database.
            tail = (result.stderr or result.stdout or "").strip().splitlines()
            raise RuntimeError(
                f"spotdl exited {result.returncode}: "
                + (" | ".join(tail[-3:]) if tail else "no output")
            )
        audio_files = [
            f for f in job_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
        if not audio_files:
            raise FileNotFoundError(f"spotdl produced no audio file for {spotify_url}")
        return audio_files[0]
    except Exception:
        # A failed download has to clean up its own temp dir here, because only a
        # returned path ever reaches cleanup().
        shutil.rmtree(job_dir, ignore_errors=True)
        raise


def load_audio(audio_path: Path) -> np.ndarray:
    # Mirrors SpotifyIngestService._load_audio. 16 kHz mono is what the model wants and
    # what the corpus was embedded from; both numbers matter.
    return MonoLoader(
        filename=str(audio_path), sampleRate=16000, resampleQuality=4
    )()


def cleanup(audio_path: Path) -> None:
    # Remove the per-download temp dir (the direct child of DOWNLOADS_DIR), so spotdl's
    # stray files go with it. Guard hard against ever removing DOWNLOADS_DIR itself.
    try:
        top = DOWNLOADS_DIR / audio_path.relative_to(DOWNLOADS_DIR).parts[0]
        if top != DOWNLOADS_DIR and top.is_dir():
            shutil.rmtree(top, ignore_errors=True)
            return
    except (ValueError, IndexError):
        pass
    if audio_path.exists():
        os.remove(audio_path)
