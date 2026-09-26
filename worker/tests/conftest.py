"""Put `worker/` on the path so the modules import by their own names.

The worker is a script, not a package — `run.py` does `from client import ...` and relies
on the script's own directory being sys.path[0]. Tests import the same way, so they need
the same thing arranged for them.

Only `client.py` is exercised here, and it imports nothing but `requests`. That is
deliberate: `audio.py` and `run.py` import essentia and load an 18 MB model at import
time, which is why the CI job for this can run on a bare runner with two pip installs
instead of the backend image.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
