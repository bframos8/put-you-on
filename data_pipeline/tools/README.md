Tool classes utilized in data pipeline:

    1. database_manager.py
        Class: DatabaseManager
        Public Functions: 
            connect() -> None, close() -> None, 
            insert_row(table_name: str, column_names: list[str], data: list) -> None, 
            insert_row_and_return_id(table_name: str, column_names: list[str], data: list) -> int,
            execute_query() -> list
        Features:
            Defence against SQL Injection using SQL security principles.
            Works with different databases. 
            Abstracts away the task of connecting to database.
            Generic enough to be reused by other classes.
        Technologies:
            PostgreSQL
            Psycopgl
            SQL Identifiers, Placeholders, Formatting

    2. database_initializer.py
        Class: DatabaseInitializer
        Public Functions: 
            create_table(table_name: str, column_names:list[str]) -> None,
            create_type(type_name: str, values: list[str]) -> None
        Features:
            Dependency Injection from DatabaseManager to reuse code. 
            Defence against SQL Injection using SQL security principles.
        Technologies:
            PostgreSQL
            Psycopgl
            SQL Identifiers, Placeholders, Formatting

    3. bandcamp_crawler.py
        Class: BandcampCrawler
        Public Functions: 
            run() -> None,
            get_discover_payloads() -> list
        Features: 
            Exponential backoff. 
            Stale content checking. 
            Statistics logging. 
        Technologies:
            Json
            Regex
            Time
            Playwright

    4. datamodels.py
        Dataclasses:
            AlbumMetadata
            AudioWithMetadata
            EmbeddingWithMetadata
            Song(deprecated)
        Features:
            Python Dataclass 
            Path
            Numpy
        
