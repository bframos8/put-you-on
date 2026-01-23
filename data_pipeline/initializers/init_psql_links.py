import os
from pathlib import Path
from dotenv import load_dotenv

from local.tools.database_manager import DatabaseManager
from local.tools.database_initializer import DatabaseInitializer

# Load environment variables from .env-postgres in project root
env_path = Path(__file__).resolve().parents[2] / ".env-postgres"
load_dotenv(dotenv_path=env_path)

DB_NAME = os.getenv("POSTGRES_DB")
USER = os.getenv("POSTGRES_USER")
PASSWORD = os.getenv("POSTGRES_PASSWORD")
HOST = os.getenv("POSTGRES_HOST", "localhost")
PORT = os.getenv("POSTGRES_PORT", "5432")

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

    # Enable pgvector extension for embeddings
    db_manager.cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    db_manager.conn.commit()
    print("pgvector extension enabled.")

    # Create the work_status_enum type
    db_initializer.create_type(
        "work_status_enum",
        ["pending", "in_progress", "completed", "failed"])

    # Create the artists table first (albums references it)
    db_manager.cur.execute("""
        CREATE TABLE IF NOT EXISTS artists (
            id SERIAL PRIMARY KEY,
            bandcamp_band_id BIGINT UNIQUE,
            url TEXT,
            band_name TEXT,
            band_location TEXT
        );
    """)
    db_manager.conn.commit()
    print("Table 'artists' created successfully.")

    # Create the albums table
    db_manager.cur.execute("""
        CREATE TABLE IF NOT EXISTS albums (
            id SERIAL PRIMARY KEY,
            title TEXT DEFAULT 'Void',
            external_source_id BIGINT UNIQUE,
            source TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP,
            url TEXT DEFAULT 'Void',
            duration INTEGER,
            release_date TEXT,
            artist_name TEXT,
            artist_id INTEGER REFERENCES artists(id),
            work_status work_status_enum DEFAULT 'pending'
        );
    """)
    db_manager.conn.commit()
    print("Table 'albums' created successfully.")

    # Drop and recreate the songs table with correct embedding vector size
    db_manager.cur.execute("DROP TABLE IF EXISTS songs;")
    db_manager.conn.commit()

    db_manager.cur.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id SERIAL PRIMARY KEY,
            title TEXT,
            artist_name TEXT,
            album_title TEXT,
            album_id INTEGER REFERENCES albums(id),
            embedding vector(1280),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );
    """)
    db_manager.conn.commit()
    print("Table 'songs' created successfully.")

    db_manager.close()
    
if __name__ == "__main__":
    init_pyo_db()