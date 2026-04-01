import json
from pathlib import Path

from data_pipeline.link_pipeline.crawler import BandcampCrawler
from data_pipeline.db.manager import DatabaseManager
from data_pipeline.config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

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

def run_pipeline(db_manager):
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

        # Skip albums already seen this run
        candidate_items = [item for item in payload if item.get("item_id") not in album_cache]
        cache_skipped = len(payload) - len(candidate_items)

        # Skip albums already in the DB (check only the IDs we're about to try)
        candidate_ids = [item.get("item_id") for item in candidate_items]
        existing_in_db = db_manager.fetch_existing_values("albums", "external_source_id", candidate_ids)
        # Deduplicate within payload by item_id, then exclude DB-existing
        seen_this_payload: set = set()
        new_items = []
        for item in candidate_items:
            iid = item.get("item_id")
            if iid not in existing_in_db and iid not in seen_this_payload:
                seen_this_payload.add(iid)
                new_items.append(item)
        db_skipped = len(candidate_items) - len(new_items)

        # Batch upsert any artists not yet in cache
        unseen_band_ids = {item.get("band_id") for item in new_items if item.get("band_id") not in artist_cache}
        if unseen_band_ids:
            seen: set = set()
            artist_rows = []
            for item in new_items:
                band_id = item.get("band_id")
                if band_id in unseen_band_ids and band_id not in seen:
                    seen.add(band_id)
                    artist_rows.append((
                        item.get("band_id"),
                        item.get("band_name"),
                        item.get("band_url").partition("?")[0],
                        item.get("band_location"),
                    ))
            db_manager.insert_rows_ignore_conflicts(
                "artists",
                ["bandcamp_band_id", "band_name", "url", "band_location"],
                artist_rows,
            )
            artist_cache.update(db_manager.fetch_id_map("artists", "bandcamp_band_id", list(unseen_band_ids)))

        # Batch insert albums
        album_rows = [
            (
                item.get("title"),
                item.get("item_id"),
                "bandcamp",
                item.get("item_url").partition("?")[0],
                item.get("item_duration"),
                item.get("release_date"),
                item.get("band_name"),
                artist_cache.get(item.get("band_id")),
                "pending",
                f'https://f4.bcbits.com/img/a{item.get("primary_image").get("image_id")}_0.jpg',
                genre,
            )
            for item in new_items
        ]

        if album_rows:
            db_manager.insert_rows_ignore_conflicts(
                "albums",
                [
                    "title", "external_source_id", "source",
                    "url", "duration", "release_date",
                    "artist_name", "artist_id",
                    "work_status", "image_url", "genre",
                ],
                album_rows,
            )
            for item in new_items:
                album_cache[item.get("item_id")] = True

        print(f"Completed {genre}: {len(album_rows)} inserted, {db_skipped} already in DB, {cache_skipped} cache skips")

        # Mark genre as processed and save progress
        genre_urls[url] = False
        save_progress(genre_urls)

    print(f"\n{'='*50}")
    print(f"All genres complete. Total unique artists: {len(artist_cache)}, Total unique albums: {len(album_cache)}")


if __name__ == "__main__":
    db_manager = DatabaseManager(
        db_name=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    db_manager.connect()
    run_pipeline(db_manager)
    db_manager.close()
