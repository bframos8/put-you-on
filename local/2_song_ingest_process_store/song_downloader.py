import subprocess
import tempfile
from tools.datamodels import Song
from pipeline_stage import PipelineStage
from tools.database_manager import DatabaseManager
from pathlib import Path

class SongDownloader(PipelineStage):
    def __init__(self, output_queue):
        super().__init__(name="SongDownloader")
        self.db_manager = DatabaseManager(
            db_name="put_you_on_db",
            user="ramos",
            password="",
            host="localhost",
            port="5432"
        )
        self.db_manager.connect()
        self.output_queue = output_queue
        
    def run(self):
        urls_to_download = self._get_urls_to_download()
        for song_id, url in urls_to_download:
            self.download_songs(url)
            self.output_queue.put((song_id, url))
        
        
    def _get_urls_to_download(self):
        query = "SELECT id, title, artist_name, url FROM albums WHERE download_status_enum = pending;"
        results = self.db_manager.execute_query(query)
        return [row for row in results]
    
    def _download_songs(self, url: str) -> None:
        temp_path = self._get_temp_dir()
        subprocess.run([
            "bandcamp-dl",
            "--base-dir",
            temp_path,
            f'{url}',
        ])
        
    
    def _get_temp_dir(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        return Path(temp_dir.name)