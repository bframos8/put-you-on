from local.tools.database_manager import DatabaseManager
from local.tools.database_initializer import DatabaseInitializer

DB_NAME = "put_you_on_db"
USER = "ramos"
PASSWORD = ""
HOST = "localhost"
PORT = "5432"

def init_pyo_db():
    db_manager = DatabaseManager(
        db_name=DB_NAME,
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT
    )
    db_manager.connect()
    
    db_initializer = DatabaseInitializer(db_manager)
    
    # Create the download_status_enum type
    db_initializer.create_type(
        "download_status_enum", 
        ["pending", "in_progress", "completed", "failed"])
    
    # Create the scraped_links table
    db_initializer.create_table(
        "scraped_links", 
        ["url TEXT PRIMARY KEY", 
         "download_status download_status_enum NOT NULL", 
         "first_seen TIMESTAMP DEFAULT NOW()"])
    
    db_manager.close()
    
if __name__ == "__main__":
    init_pyo_db()