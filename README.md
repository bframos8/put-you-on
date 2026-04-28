# put-you-on

App flow: 

- User logs into Spotify Account using OAuth
- This creates a user in database with corresponding Spotify metadata  
- Top Songs are downloaded from Youtube 
- Audio files are run through Essentia Model for embeddings
- Embeddings and metadata are added to database with a flag to not use song as a recommendation 
- Call on 10 closest neighbors per song, cache in metadata of song.
- Give 10 recommended songs per day max. 


Tech Stack for active web application: 

- Frontend: Built using Typescript, Javascript, CSS, and HTML via React with Next.js hosted on AWS EC2. 
    - Testing: Typescript check and manual checks of documentation from next.js and endpoint checks via browser. 

- Backend: Built using Python via FastAPI. Implemented RESTful API to enable auth flow, user ingestion, and recommendation pipelines. Hosted on AWS EC2. 
    - Testing: Full suite of tests in Python using Pytest and Unittest libraries. 

- Database: Deployed relational database via PostgreSQL 16.13 with PGVector extension. Utilizes enums for restricting entries. Uses indexing and relations for quick recommendations via vector search. Hosted on AWS Relational Database Service (RDS). 

- DevOps: Git Actions automatically runs test suites on a PR. If tests pass and after manual check, new version is deployed via Docker and Docker compose onto AWS EC2 instance. 


Data pipeline for database populating: 

- Nightly Cron Jobs for two different stages.

- Cron Job 1: Web-crawler using Python via Playwright to extract new album website links from every main category in BandCamp. 
    - Adds album link to database if link has not been cached in session history or in database. 

- Cron Job 2: Process album links and insert songs into database via a feeder-consumer design pattern with each job on a different core (Python has the GLI so not exactly parallel). 
    - Web-scrape audio files and metadata using BandCamp-dl library
    - Audio files are ran through Essentia Model for vector embedding
    - Audio files are deleted to save memory and adhere to standard policies. 
    - Embedding and audio metadata is inserted into songs table in database. 



# Project Steps
Development Phase 1: 

1. Setup local Postgres database for link checking capabilities 
    1. album, song, artist tables to start.

2. Setup locally run web-crawler that feeds into local PostgreSQL.
3. Optionally containerize 

Development Phase 2: 

1. Setup locally run scraper that downloads each album from album table links 
2. Process songs and insert into local PostgreSQL.
3. Optionally contanerize 

Developments Phase 3: 

1. Deploy database onto AWS RDS and run nightly Cron Jobs for pipelines. 
1. Start new next.js project 
2. Create the api calls 
3. Create the front end that hooks up to backend 
4. Once working correctly and stable, containerize and send to AWS EC2 

Disclaimer: 
This app stores your Spotify ID, display name, email, and OAuth tokens; tokens are used to fetch your top tracks; data is stored in Postgres on AWS RDS in us-east-1.





