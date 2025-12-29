from song_embedder import SongEmbedder
from phase_1.database_manager import DatabaseManager

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