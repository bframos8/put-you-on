Development Phase 2: 

Creating the data pipeline starting from the scraped album inserted into the database 
via phase 1 development. Use producer vs consumer technique with multithreading.  

Downloader -> AudioQueue -> Embedder -> EmbedQueue -> DBWriter 

1. Create the downloader class, the producer 
    1. Feeds to AudioQueue 
    2. Flushes per album since audio files are large. 

2. Create the Embedder class
    1. Feeds to EmbedQueue
    2. Flushes at argument size provided

3. Create the DBWriter Class 
    1. Feeds into PostgreSQL docker image