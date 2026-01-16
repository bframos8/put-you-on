import sys
from pathlib import Path

# Add pipeline modules to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "local" / "2_song_ingest_process_store"))
sys.path.insert(0, str(project_root / "local"))
