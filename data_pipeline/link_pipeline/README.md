Development Phase 1: 

1. Setup local Postgres database for link checking capabilities 
    1. scraped_links table

NOTES:

    *Created two custom database classes to help with initializing and managing this database
    and any future database functions will be added to these classes. 
    *Both classes stick to security principles in SQL to avoid risk from SQL injection. 
    *Utilized dependency injection between the classes to reuse code. 

2. Setup locally run web-crawler that feeds into local Postgres 

NOTES: 
    
    *Created a custom crawler class to automate the crawl
    *Returns the album objects ready for ingestion into the database
    *Created a script that takes the targeted data to create an artist row and an album row
    *Utilized caching in memory via a dict to avoid redundant returns of artist ID's from database per session

3. Setup locally run docker container script that feeds initial songs into local docker Postgres

4. (Optional) Once these work correctly and are stable, send containers into AWS cloud
