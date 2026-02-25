import json
import os
from pathlib import Path
from dotenv import load_dotenv

from data_pipeline.tools.bandcamp_crawler import BandcampCrawler
from data_pipeline.tools.database_manager import DatabaseManager

# Load environment variables from .env-postgres in project root
env_path = Path(__file__).resolve().parents[2] / ".env-postgres"
load_dotenv(dotenv_path=env_path)

DB_NAME = os.getenv("POSTGRES_DB")
USER = os.getenv("POSTGRES_USER")
PASSWORD = os.getenv("POSTGRES_PASSWORD")
HOST = os.getenv("POSTGRES_HOST", "localhost")
PORT = os.getenv("POSTGRES_PORT", "5432")

DEFAULT_GENRE_URLS = {
    "https://bandcamp.com/discover/reggae/digital?s=new": True,
    "https://bandcamp.com/discover/country/digital?s=new": True,
    "https://bandcamp.com/discover/blues/digital?s=new": True,
    "https://bandcamp.com/discover/latin/digital?s=new": True,
    "https://bandcamp.com/discover/all/digital?s=new": True,
    "https://bandcamp.com/discover/electronic/digital?s=new": True,
    "https://bandcamp.com/discover/rock/digital?s=new": True,
    "https://bandcamp.com/discover/metal/digital?s=new": True,
    "https://bandcamp.com/discover/alternative/digital?s=new": True,
    "https://bandcamp.com/discover/hip-hop-rap/digital?s=new": True,
    "https://bandcamp.com/discover/experimental/digital?s=new": True,
    "https://bandcamp.com/discover/punk/digital?s=new": True,
    "https://bandcamp.com/discover/folk/digital?s=new": True,
    "https://bandcamp.com/discover/pop/digital?s=new": True,
    "https://bandcamp.com/discover/ambient/digital?s=new": True,
    "https://bandcamp.com/discover/soundtrack/digital?s=new": True,
    "https://bandcamp.com/discover/world/digital?s=new": True,
    "https://bandcamp.com/discover/jazz/digital?s=new": True,
    "https://bandcamp.com/discover/acoustic/digital?s=new": True,
    "https://bandcamp.com/discover/funk/digital?s=new": True,
    "https://bandcamp.com/discover/r-b-soul/digital?s=new": True,
    "https://bandcamp.com/discover/classical/digital?s=new": True,
}

PROGRESS_FILE = Path(__file__).parent / "genre_progress.json"


def load_progress():
    """Load progress from JSON file, or return defaults if not found."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r") as f:
            genre_progress = json.load(f)
            if not any(genre_progress.values()):
                genre_progress = DEFAULT_GENRE_URLS.copy()
            return genre_progress
    return DEFAULT_GENRE_URLS.copy()


def save_progress(genre_urls:dict):
    """Save current progress to JSON file."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(genre_urls, f, indent=2)

if __name__ == "__main__":
    db_manager = DatabaseManager(
        db_name=DB_NAME,
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT
    )
    db_manager.connect()

    artist_cache = {}  # Persist across all genres to avoid duplicate artists
    album_cache = {}   # Persist across all genres to avoid duplicate albums

    genre_urls = load_progress()

    for url, should_process in genre_urls.items():
        if not should_process:
            continue
        genre = url.split("/")[4]  # Extract genre from URL
        print(f"\n{'='*50}")
        print(f"Crawling genre: {genre}")
        print(f"{'='*50}")

        crawler = BandcampCrawler(url)
        crawler.run()
        payload = crawler.get_discover_payloads()
        albums_inserted = 0
        for item in payload:
            album_external_id = item.get("item_id")
            if album_external_id in album_cache:
                print(f'ALBUM ID {external_id} found in cache, skipping.')
                continue  # Skip duplicate album

            external_id = item.get("band_id")
            if external_id in artist_cache:
                db_artist_id = artist_cache[external_id]
            else:
                db_artist_id = db_manager.upsert_row_and_return_id(
                    table_name="artists",
                    column_names=["bandcamp_band_id", "band_name", "url", "band_location"],
                    data=[
                        item.get("band_id"),
                        item.get("band_name"),
                        item.get("band_url").partition("?")[0],
                        item.get("band_location")
                    ],
                    conflict_column="bandcamp_band_id"
                )
                artist_cache[external_id] = db_artist_id

            album_url = item.get("item_url").partition("?")[0]

            was_inserted = db_manager.upsert_row(
                table_name="albums",
                column_names=[
                    "title", "external_source_id", "source",
                    "url", "duration", "release_date",
                    "artist_name", "artist_id",
                    "work_status", "image_url"
                ],
                data=[
                    item.get("title"),
                    album_external_id,
                    "bandcamp",
                    album_url,
                    item.get("item_duration"),
                    item.get("release_date"),
                    item.get("band_name"),
                    db_artist_id,
                    "pending",
                    f'https://f4.bcbits.com/img/a{item.get("primary_image").get("image_id")}_0.jpg'
                ],
                conflict_column="external_source_id"
            )
            if was_inserted:
                album_cache[album_external_id] = True
                albums_inserted += 1

        print(f"Completed {genre}: {albums_inserted} albums inserted ({len(payload) - albums_inserted} duplicates skipped)")

        # Mark genre as processed and save progress
        genre_urls[url] = False
        save_progress(genre_urls)
        

    print(f"\n{'='*50}")
    print(f"All genres complete. Total unique artists: {len(artist_cache)}, Total unique albums: {len(album_cache)}")
    db_manager.close()