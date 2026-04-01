from data_pipeline.db.manager import DatabaseManager
from data_pipeline.db.initializer import DatabaseInitializer
from data_pipeline.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

def init_pyo_db():
    db_manager = DatabaseManager(
        db_name=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
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

    # Drop and recreate the songs table with correct embedding vector size
    db_manager.cur.execute("DROP TABLE IF EXISTS albums CASCADE;")
    db_manager.conn.commit()
    # Create the albums table
    db_manager.cur.execute("""
        CREATE TABLE IF NOT EXISTS albums (
            id SERIAL PRIMARY KEY,
            title TEXT DEFAULT 'Void',
            external_source_id BIGINT UNIQUE,
            source TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP,
            url TEXT UNIQUE DEFAULT 'Void',
            duration INTEGER,
            release_date TEXT,
            artist_name TEXT,
            artist_id INTEGER REFERENCES artists(id),
            work_status work_status_enum DEFAULT 'pending',
            image_url TEXT,
            genre TEXT
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
            is_candidate BOOLEAN NOT NULL DEFAULT TRUE,
            spotify_track_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            UNIQUE (album_id, title)
        );
    """)
    db_manager.conn.commit()
    print("Table 'songs' created successfully.")

    db_manager.cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            spotify_id TEXT UNIQUE NOT NULL,
            display_name TEXT,
            email TEXT UNIQUE,
            spotify_access_token TEXT,
            spotify_refresh_token TEXT,
            token_expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    db_manager.conn.commit()
    print("Table 'users' created successfully.")

    db_manager.cur.execute("""
        CREATE TABLE IF NOT EXISTS user_top_songs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            song_id INTEGER REFERENCES songs(id),
            spotify_track_id TEXT NOT NULL,
            spotify_url TEXT,
            image_url TEXT,
            artist_name TEXT,
            track_title TEXT,
            album_title TEXT,
            snapshot_at TIMESTAMP DEFAULT NOW(),
            used_as_query BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)
    db_manager.conn.commit()
    print("Table 'user_top_songs' created successfully.")

    db_manager.cur.execute("""
        CREATE TABLE IF NOT EXISTS user_recommendations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            song_id INTEGER NOT NULL REFERENCES songs(id),
            recommended_at TIMESTAMP DEFAULT NOW()
        );
    """)
    db_manager.conn.commit()
    print("Table 'user_recommendations' created successfully.")

    db_manager.close()

if __name__ == "__main__":
    init_pyo_db()
