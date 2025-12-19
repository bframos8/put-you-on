Development Phase 1: 

1. Setup local Postgres database for link checking capabilities 
    1. scraped_links table

NOTES:

    *Created two database classes to help with initializing and managing this database
    and any future database functions will be added to these classes. 
    *Both classes stick to security principles in SQL to avoid risk from SQL injection. 
    *Utilized dependency injection between the classes to reuse code. 

2. Setup locally run web-crawler that feeds into local Postgres 
3. Setup locally run docker container script that feeds initial songs into local Postgres
4. Once these work correctly and are stable, send containers into AWS cloud
