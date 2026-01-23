from dataclasses import dataclass
from pathlib import Path
import numpy as np

@dataclass
class AlbumMetadata:
    """Metadata from the albums table"""
    album_id: int
    title: str
    artist_name: str
    url: str
    # Add any other columns you need here

@dataclass
class AudioWithMetadata:
    """Audio file path with associated album metadata"""
    file_path: Path
    metadata: AlbumMetadata

@dataclass
class EmbeddingWithMetadata:
    """Song embedding with metadata for database insertion"""
    file_path: Path
    embedding: np.ndarray
    metadata: AlbumMetadata

@dataclass
class Song:
    """Legacy song dataclass - kept for compatibility"""
    id: int
    title: str
    artist: str
    album: str
    filepath: str
    embedding: list