"""Worker configuration, read from the environment (gameplan 10.6).

Mirrors the app's contract: plain environment variables, loaded from a local gitignored
`.env` next to this file. The worker runs outside AWS and gets no AWS or database
credentials — it talks to the app over HTTPS and nothing else.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# Where the app lives. https://putyouon.app in production; https://127.0.0.1 for a local
# docker compose stack.
API_URL = os.getenv("PUTYOUON_API_URL", "https://putyouon.app").rstrip("/")

# The shared secret for /api/v1/ingest/*. Same value as the INGEST_WORKER_TOKEN parameter
# in SSM. Without it the endpoints answer 404 and this worker has nothing to talk to.
WORKER_TOKEN = os.getenv("INGEST_WORKER_TOKEN", "")

# spotdl needs its own Spotify credentials to resolve a track URL. These are the same
# client id/secret the app uses. This is the part of the design where secrets genuinely
# leave the AWS boundary, by hand.
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# How many seeds to lease at once. Small on purpose: the claim expires on the server after
# a fixed lease, so anything this worker cannot finish inside it gets handed out again.
BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "3"))

# Poll fast while there is work, slowly when there is not. Nobody is waiting during an
# idle stretch, and a new user's first request is what creates work in the first place —
# so the busy interval is the one that shows up as someone watching a spinner.
BUSY_POLL_SECONDS = float(os.getenv("WORKER_BUSY_POLL_SECONDS", "10"))
IDLE_POLL_SECONDS = float(os.getenv("WORKER_IDLE_POLL_SECONDS", "60"))

HTTP_TIMEOUT = float(os.getenv("WORKER_HTTP_TIMEOUT", "30"))

# The JavaScript runtime yt-dlp uses to solve YouTube's player challenge. It needs one —
# extraction without it is deprecated and yields formats with no URLs — and it enables
# only Deno by default, which most machines do not have. Node does, if anything here
# builds a frontend. Must be on PATH; run.py checks at startup.
JS_RUNTIME = os.getenv("WORKER_JS_RUNTIME", "node")

# Hard ceiling on one spotdl call. A measured track takes about 70 seconds including
# the embedding, so ten minutes is generous; the point is that a hung download cannot
# hold the worker indefinitely while its server-side lease expires underneath it.
DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("WORKER_DOWNLOAD_TIMEOUT_SECONDS", "600"))

# TLS verification, on unless explicitly disabled. The ONLY reason to turn this off is a
# local stack behind mkcert certificates, which the system trusts but Python (certifi)
# does not. Never set it false against a real host: the bearer token would be sent to
# whoever answered.
VERIFY_TLS = os.getenv("WORKER_VERIFY_TLS", "true").lower() != "false"
