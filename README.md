# put-you-on

Service backend:

- User logs into Spotify Account using OAuth
- This creates a user in database with corresponding Spotify metadata 
- Top songs are accessed 
- Songs are downloaded from Youtube 
- Audio files are run through Essentia Model for embeddings
- Embeddings and metadata are added to database with a flag to not use song as a recommendation 
- Call on 10 closest neighbors per song, cache in metadata of song.
- Give 10 recommended songs per day max. 


Tech Stack for active website:

- React with Next.js -> AWS App Runner 
    - App runner allows for server side rendering

- Simple API implementing OAuth through Next.js -> AWS App Runner
    - Mitigates the need for another separate service for API's however this might become a problem if I want to use an app later on. 

- PostgreSQL with PGVector extension -> AWS Relational Database Service (RDS)
    - allows for quick recommendations with built in extension



Daily backend for data extraction: -> Nightly routine run locally through Docker Image for future scalability 

- Web-crawler using playwright to extract new album website links from every main category in BandCamp
    - Adds to list if link has not been seen with seen boolean set to false

- Process a single album link and insert into database
    - Web-scrape audio files and metadata using BandCamp-dl library
    - Sets seen boolean to true once downloaded in list
    - Audio files are ran through Essentia Model for vector embedding
    - Audio files are deleted to save memory
    - Embedding and audio metadata is inserted into database



# Project Steps
Development Phase 1: 

1. Setup local Postgres database for link checking capabilities 
    1. album table 

2. Setup locally run web-crawler that feeds into local Postgres 
3. Optionally containerize 
Development Phase 2: 

1. Setup locally run scraper that downloads each album from album table to local storage for batch processing
2. Setup locally run 
Developments Phase 3: 

1. Start new next.js project 
2. Create the api calls 
3. Create the front end that hooks up to backend 
4. Once working correctly and stable, containerize and send to AWS App runner 








