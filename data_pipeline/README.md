Locally Run Data Pipeline

Once PSQL database is initilized,
1. Album Link Ingestion -> Store in PSQL
2. Album Links -> Ingest Audio -> Process via model -> Store in PSQL
3. Contanerize for future cloud deployment

For security reasons, some initialization files have been excluded.
Example files have been provided instead. 

Notes on Claude Changes: 

Summary
I've successfully implemented metadata flow through your entire pipeline. Here's what changed:
1. Created Shared Dataclasses (local/tools/datamodels.py)
AlbumMetadata: Holds album info (album_id, title, artist_name, url)
AudioWithMetadata: Pairs audio file paths with album metadata
EmbeddingWithMetadata: Pairs embeddings with metadata for DB insertion
2. Updated SongDownloader (local/2_song_ingest_process_store/song_downloader.py)
Queries albums table for metadata (id, title, artist_name, url)
Creates AlbumMetadata object for each album
Downloads songs and wraps each audio file with metadata as AudioWithMetadata
Puts AudioWithMetadata objects into the audio_queue
Fixed temp directory handling (keeps reference to prevent premature deletion)
Fixed SQL query (added quotes around 'pending')
3. Updated SongEmbedder (local/2_song_ingest_process_store/song_embedder.py)
Receives AudioWithMetadata from audio_queue
Embeds the audio and creates EmbeddingWithMetadata
Passes metadata forward to embed_queue
Inherits from PipelineStage for threading
4. Updated SongDBWriter (local/2_song_ingest_process_store/song_dbwriter.py)
Receives EmbeddingWithMetadata from embed_queue
Extracts metadata for database insertion
Inserts songs with album_id (foreign key), artist_name, album title, and embedding
Data Flow:

Albums Table → AlbumMetadata → AudioWithMetadata → EmbeddingWithMetadata → Songs Table
Note: In song_dbwriter.py:44, I used item.file_path.stem as the song title. You may want to parse this differently depending on how bandcamp-dl names files. To add more columns: Simply add fields to AlbumMetadata in datamodels.py and update the query in song_downloader.py:49.