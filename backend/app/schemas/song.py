from pydantic import BaseModel
from ..db.models import Song


class RecsResponse(BaseModel):
    query_title: str
    query_artist: str
    recommendations: list["SongResponse"]


class SongResponse(BaseModel):
    id: int
    title: str
    artist_name: str
    album_title: str
    image_url: str | None
    external_source_id: int | None
    album_url: str | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_song(cls, song: Song) -> "SongResponse":
        return cls(
            id=song.id,
            title=song.title,
            artist_name=song.artist_name,
            album_title=song.album_title,
            image_url=song.album.image_url if song.album else None,
            external_source_id=song.album.external_source_id if song.album else None,
            album_url=song.album.url if song.album else None,
        )
