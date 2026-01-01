from dataclasses import dataclass

@dataclass
class Song:
    id: int
    title: str
    artist: str
    album: str
    filepath: str
    embedding: list