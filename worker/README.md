# Ingest worker

Downloads and embeds a user's Spotify seed tracks on a machine with a residential IP,
and posts the results back to the app. Gameplan 10.6.

## Why this exists

The production EC2 instance cannot download audio. YouTube bot-challenges its datacenter
address:

```
ERROR: [youtube] Sign in to confirm you're not a bot.
```

It has never worked on that box. Existing users are unaffected because their seeds were
processed before the instance was built, but no new user can be onboarded. Gameplan 10.3
ruled out the obvious explanations by measurement, not guesswork: the yt-dlp version was
already the newest published, a master build behaved identically, all seven player
clients were blocked, the alternative spotdl providers route through yt-dlp anyway, and
Spotify's `preview_url` was deprecated for new apps in 2024. A residential IP is what
actually changes the outcome.

So the download moves off AWS. The app keeps a queue; this worker drains it.

One correction to that story, learned while building this. A residential IP is
*necessary* but it was not *sufficient*: the first run from a residential connection also
failed, and neither reason was the address. spotdl aborted with *"You are blocked by
YouTube Music. Please use a VPN"* — a false alarm from a pre-flight check that searches
for the letter `"a"` unfiltered and miscounts the result — and then yt-dlp failed for want
of a JavaScript runtime. `audio.py` passes the two flags that fix both. **Do not trust a
spotdl failure message to name its own cause.**

## Shape

The worker dials out. It never accepts a connection, holds no AWS or database
credentials, and the database keeps its private subnet.

```
worker  ──POST /api/v1/ingest/claim────►  lease up to N pending seeds
        ◄─ jobs: [{id, spotify_url, …}]

        (download with spotdl, classify, embed — all local)

        ──POST /api/v1/ingest/complete─►  {id, genre, embedding[1280]}
        ──POST /api/v1/ingest/fail─────►  {id, error}
```

A claim is a **lease**, not a lock: it expires server-side after 15 minutes. Kill this
process whenever you like — anything in flight is handed out again once the lease runs
out. `/complete` is idempotent, so a retry after a deploy is a no-op rather than a second
copy of the song.

The worker fills seeds. It never generates a dispatch: that stays in `get_recs`, which
holds a row lock and decides whether the user's one-a-day has been spent.

## What the machine needs

Beyond the Python dependencies, two things that are easy to miss and whose absence looks
like something else entirely:

- **A JavaScript runtime on PATH.** Current yt-dlp needs one to solve YouTube's player
  challenge, and enables only Deno by default. Without one it warns that extraction is
  deprecated, then fails with *"Requested format is not available"* — which reads like
  the video's problem, not yours. Node counts; `WORKER_JS_RUNTIME` picks another.
  `run.py` checks at startup and refuses to run without it.
- **A current yt-dlp.** Measured 2026-09-25 on one machine, minutes apart: 2026.03.03
  could not download at all, 2026.08.19 downloaded in under a second. That is why
  [worker_requirements.txt](worker_requirements.txt) gives it a floor rather than a pin.
  **When downloads start failing, upgrade yt-dlp before believing anything else.**

## Running it

```sh
python3.11 -m venv .venv
.venv/bin/pip install -r worker/worker_requirements.txt
cp worker/.env.example worker/.env      # then fill it in
PYTHONPATH=backend .venv/bin/python worker/run.py
```

One track takes about 70 seconds end to end (download, classify, embed, post), so the
default batch of 3 sits comfortably inside the server's 15-minute lease.

`PYTHONPATH=backend` lets the worker import `AudioGenreClassifier` from the app instead
of carrying its own copy of the genre mapping and a third copy of the 18 MB model file.
That module imports only numpy, essentia and a dependency-free sibling, so nothing of
FastAPI or SQLAlchemy comes with it. `run.py` also sets the path itself, so the env var
is belt and braces.

Leave it running in the background with output somewhere you can read later:

```sh
PYTHONPATH=backend nohup .venv/bin/python worker/run.py > worker/worker.log 2>&1 &
```

On a laptop, remember the machine sleeping stops the worker. `caffeinate -s` keeps it
awake while plugged in. The permanent home for this is the Mac mini under launchd
(gameplan 11.4).

## Configuration

See [.env.example](.env.example). The two that matter:

- `INGEST_WORKER_TOKEN` must equal the SSM parameter of the same name. While that is
  unset on the server, every ingest endpoint answers **404** — that is the app telling
  you it has no worker configured, not a missing route.
- `WORKER_VERIFY_TLS=false` exists only for a local stack behind mkcert certificates,
  which macOS trusts but Python does not. Never set it against a real host: the bearer
  token is sent on every request.

## Keeping the embedding honest

`audio.py` duplicates three helpers from
`backend/app/services/spotify_ingest_service.py` — download, load, embed — because
importing them would drag in the whole app. The sample rate (16 kHz), the resample
quality, the model output (`PartitionedCall:1`) and the frame-mean must match the
backend and `data_pipeline` exactly. An embedding computed differently lands in a
different space from the corpus, and nothing downstream would raise: the recommendations
would just quietly be wrong.

The same applies to the pinned `essentia-tensorflow` and `numpy` versions in
[worker_requirements.txt](worker_requirements.txt).

## When something looks wrong

If users are stuck on "Building your drop", check this worker first. A worker that is
not running produces no errors anywhere — the app simply has seeds nobody claims, which
looks identical to work in progress. The log line to look for is `Claimed N seed(s)`.
