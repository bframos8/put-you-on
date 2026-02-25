Album URL Ingestion (DP Stage 1):

Connects to postgresql database via custom DatabaseManager class (see "data_pipeline/tools/DatabaseManager.py").

Utilizes in memory cache to avoid duplicate entry's to database. In addition, the database is set to do nothing if a duplicate makes it to the database. 

Crawls 22 genre Bandcamp URLs to extract Bandcamp's album dataclasses via custom BandcampCrawler class (see "data_pipeline/tools/BandcampCrawler.py").

Checks/saves progress on genre URL's via a json file with {URL:status} key-value pairs. If value is True, the key/URL must be processed. If all values are False in initial progress loading, all values are set to True. Since this runs once a day this resets once per day. 

Extracts chosen metadata about album and artist from Bandcamp's album dataclass and inserts them into database via DatabaseManager class. 

Album art is saved into database via reverse engineered links that Bandcamp's website uses to load files to keep database memory usage low, meaning lower cost to run. 

Once all genre URL's are crawled, database connection is safely closed via the DatabaseManager class. 

Production Notes:

    *Created two custom database classes to help with initializing and managing this database
    and any future database functions will be added to these classes. 
    *Both classes stick to security principles in SQL to avoid risk from SQL injection. 
    *Utilized dependency injection between the classes to reuse code.
    *Created a custom crawler class to automate the crawl
    *Returns the album objects ready for ingestion into the database
    *Created a script that takes the targeted data to create an artist row and an album row
    *Utilized caching in memory via a dict to avoid redundant returns of artist ID's from database per session



