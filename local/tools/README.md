Classes used as tools in local data pipeline

Database classes:

    1. database_manager.py
        Class: DataBaseManager
        Public Functions: 
            connect() -> None, close() -> None, 
            insert_row(table_name: str, column_names: list[str], data: list) -> None, 
            insert_row_and_return_id(table_name: str, column_names: list[str], data: list) -> int,
            execute_query() -> list

    2. databse_initializer.py
        Class: DatabaseInitializer
        Public Functions: 
            create_table(table_name: str, column_names:list[str]) -> None,
            create_type(type_name: str, values: list[str]) -> None

    3. bandcamp_crawler.py
        Class: BandcampCrawler
        Public Functions: 
            run() -> None,
            get_discover_payloads() -> list

    4. song_downloader.py

    5. song_embedder.py 

    6. song_database_writer.py
