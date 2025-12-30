from local.tools.song_embedder import SongEmbedder
from local.tools.database_manager import DatabaseManager
import subprocess

def run_bandcamp_downloader(link:str):
    subprocess.run([
        "bandcamp-dl",
        "--base-dir",
        "./songs",
        f'{link}',
    ])

if __name__ == "__main__":
    embedder = SongEmbedder()
    
    db_manager = DatabaseManager(
        db_name="put_you_on_db",
        user="ramos",
        password="",
        host="localhost",
        port="5432"
    )
    
    db_manager.connect()
    
    