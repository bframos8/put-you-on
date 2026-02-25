Bandcamp Song/Album/Artist Data Pipeline

Once PSQL database is initilized,
1. Bandcamp's album object ingestion -> Store album and artist metadata in PSQL
2. Process album metadata and ID -> Ingest audio into local memory 
3. Process audio via Effnet model -> Store song embedding and metadata in PSQL
4. Delete audio from local memory to avoid memory usage, lowering costs. 
3. Contanerize for future cloud deployment

For security reasons, some initialization files have been excluded.
Example files have been provided instead. 
