from bandcamp_crawler import BandcampCrawler
from local.tools.database_manager import DatabaseManager

if __name__ == "__main__":
    crawler = BandcampCrawler()
    crawler.run()
    payload = crawler.get_discover_payloads()
    
    db_manager = DatabaseManager(
        db_name="put_you_on_db",
        user="ramos",
        password="",
        host="localhost",
        port="5432"
    )
    
    db_manager.connect()
    
    artist_cache = {}
    
    for item in payload:
        external_id = item.get("band_id")
        if external_id in artist_cache:
            db_artist_id = artist_cache[external_id]
        else:
            db_artist_id = db_manager.insert_row_and_return_id(
                table_name="artists",
                column_names=["external_source_id", "name", "url", "location"],
                data=[
                    item.get("band_id"),
                item.get("band_name"), 
                item.get("band_url").partition("?")[0], 
                item.get("band_location") ]
            )
            artist_cache[external_id] = db_artist_id
        
        album_url = item.get("item_url").partition("?")[0]
        
        
        
        db_manager.insert_row(
            table_name="albums",
            column_names=[
                "external_source_id", "source", 
                "title", "artist", "duration", 
                "release_date", "url", "artist_id",
                "work_status"
            ],
            data=[
                item.get("id"),
                "bandcamp",
                item.get("title"),
                item.get("band_name"),
                item.get("item_duration"),
                item.get("release_date"),
                album_url,
                db_artist_id,
                "not_started"
            ]
        )
    
    print("Data insertion complete.")
    db_manager.close()