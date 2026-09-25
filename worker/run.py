"""The ingest worker loop (gameplan 10.6).

Claims seeds from the app, downloads and embeds each one locally, posts the result back.
Runs on a machine with a residential IP, because the EC2 instance cannot download audio
at all — YouTube bot-challenges its address and no yt-dlp configuration fixes it (10.3).

Run it with the repo's backend on the path, so the genre classifier can be imported
rather than copied:

    PYTHONPATH=backend python worker/run.py

Stopping it is safe at any moment. A claim is a lease with a server-side expiry, so
anything in flight when this process dies is handed out again once the lease runs out
(INGEST_CLAIM_LEASE_SECONDS, 15 minutes). Nothing is lost; the only cost is the wait.
"""
import logging
import shutil
import signal
import sys
import time
from pathlib import Path

# The classifier comes from the backend package: `app` is a namespace package and that
# module imports only numpy, essentia and a sibling with no dependencies, so this pulls
# in none of FastAPI, SQLAlchemy or the database. Copying it instead would mean a third
# copy of the 18 MB model file in the repo and a second definition of the genre mapping.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.audio_genre_classifier import AudioGenreClassifier  # noqa: E402

from audio import Embedder, cleanup, download, load_audio  # noqa: E402
from client import ApiError, IngestClient, SeedGone  # noqa: E402
import config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

_stopping = False


def _request_stop(signum, frame):
    # Finish the track in hand, then exit. Killing mid-download would leave the seed
    # claimed until its lease expires, which is survivable but pointlessly slow.
    global _stopping
    _stopping = True
    logger.info("Stop requested; finishing the current track first")


def process(job: dict, embedder: Embedder, classifier: AudioGenreClassifier, client: IngestClient) -> None:
    """Take one claimed seed all the way to a posted result."""
    seed_id = job["id"]
    label = f"{job.get('track_title')} by {job.get('artist_name')}"
    spotify_url = job.get("spotify_url")

    if not spotify_url:
        # Nothing to download from. Report it so the seed retires at the attempt cap
        # instead of being handed out forever.
        client.fail(seed_id, "seed has no spotify_url")
        logger.warning("Seed %s (%s) has no spotify_url", seed_id, label)
        return

    started = time.monotonic()
    audio_path = None
    try:
        audio_path = download(
            spotify_url, config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET,
            js_runtime=config.JS_RUNTIME, timeout=config.DOWNLOAD_TIMEOUT_SECONDS,
        )
        audio = load_audio(audio_path)
        genre = classifier.classify(audio)
        embedding = embedder.embed(audio)
    except Exception as e:
        logger.warning("Seed %s (%s) failed: %s", seed_id, label, e)
        try:
            result = client.fail(seed_id, str(e))
            if result.get("terminal"):
                logger.warning("Seed %s retired after %s attempts", seed_id, result.get("attempts"))
        except SeedGone:
            logger.info("Seed %s vanished before its failure could be recorded", seed_id)
        return
    finally:
        if audio_path is not None:
            cleanup(audio_path)

    try:
        status = client.complete(seed_id, genre, embedding)
    except SeedGone:
        # The user's top tracks moved on while this was downloading, so the row is gone.
        # The work is wasted, not broken.
        logger.info("Seed %s vanished before its result could be stored", seed_id)
        return

    logger.info(
        "Seed %s (%s) done in %.1fs: genre=%s, status=%s",
        seed_id, label, time.monotonic() - started, genre, status,
    )


def main() -> int:
    if not config.WORKER_TOKEN:
        logger.error("INGEST_WORKER_TOKEN is not set. Copy worker/.env.example to worker/.env.")
        return 1
    if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
        logger.error("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are required by spotdl.")
        return 1
    if shutil.which("spotdl") is None:
        logger.error("spotdl is not on PATH. Install worker/worker_requirements.txt.")
        return 1
    if shutil.which(config.JS_RUNTIME) is None:
        # Checked up front because the failure without it is unhelpful: yt-dlp reports
        # "Requested format is not available", which reads like the video's problem.
        logger.error(
            "JavaScript runtime %r is not on PATH. yt-dlp needs one for YouTube; "
            "install it or set WORKER_JS_RUNTIME.", config.JS_RUNTIME,
        )
        return 1
    if not config.VERIFY_TLS:
        logger.warning(
            "TLS verification is OFF. Only ever do this against a local stack — the "
            "worker token is sent on every request."
        )

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    logger.info("Loading models")
    embedder = Embedder()
    classifier = AudioGenreClassifier()
    client = IngestClient(
        config.API_URL, config.WORKER_TOKEN, config.HTTP_TIMEOUT, verify=config.VERIFY_TLS
    )
    logger.info("Worker ready, polling %s every %ss (idle: %ss)",
                config.API_URL, config.BUSY_POLL_SECONDS, config.IDLE_POLL_SECONDS)

    while not _stopping:
        try:
            jobs, lease_seconds = client.claim(config.BATCH_SIZE)
        except ApiError as e:
            # A 401/404 is a configuration problem and will not fix itself, but exiting
            # would mean a typo in the token takes the worker down until someone notices.
            # Log it loudly and keep polling slowly.
            logger.error("Claim failed: %s", e)
            time.sleep(config.IDLE_POLL_SECONDS)
            continue
        except Exception as e:
            # Connection refused, a timeout, a 502 — the app is very likely mid-deploy
            # (8.3 recreates the containers). Back off and try again.
            logger.warning("Could not reach the app: %s", e)
            time.sleep(config.IDLE_POLL_SECONDS)
            continue

        if not jobs:
            time.sleep(config.IDLE_POLL_SECONDS)
            continue

        logger.info("Claimed %d seed(s), lease %ss", len(jobs), lease_seconds)
        batch_started = time.monotonic()
        for job in jobs:
            try:
                process(job, embedder, classifier, client)
            except Exception as e:
                # process() already reports an ingest failure to the app; reaching here
                # means the reporting itself failed — a 5xx, a 422, a dropped connection
                # mid-deploy. Log it and move on. This worker is meant to run for weeks,
                # so nothing about one seed may be allowed to end the loop. The seed stays
                # claimed and comes back when its lease expires.
                logger.error("Seed %s could not be reported: %s", job.get("id"), e)
            if _stopping:
                break
        elapsed = time.monotonic() - batch_started
        if lease_seconds and elapsed > lease_seconds:
            # The tail of this batch may have been handed to another worker, or to this
            # one on its next poll. Not harmful — /complete is idempotent — but it means
            # the batch size is too big for the lease.
            logger.warning(
                "Batch took %.0fs, longer than the %ss lease; lower WORKER_BATCH_SIZE",
                elapsed, lease_seconds,
            )

        time.sleep(config.BUSY_POLL_SECONDS)

    logger.info("Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
