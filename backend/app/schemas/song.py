from pydantic import BaseModel
from ..db.models import Song, UserTopSong


class RecsResponse(BaseModel):
    status: str = "ready"
    query_title: str | None = None
    query_artist: str | None = None
    recommendations: list["SongResponse"] = []
    locked_for_today: bool = False
    next_dispatch_at: str | None = None


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


class TopTrackItem(BaseModel):
    id: str
    title: str | None
    artist_name: str | None
    album_title: str | None
    image_url: str | None
    album_url: str | None
    duration_ms: int | None = None
    popularity: int | None = None

    @classmethod
    def from_user_top_song(cls, row: UserTopSong) -> "TopTrackItem":
        return cls(
            id=row.spotify_track_id,
            title=row.track_title,
            artist_name=row.artist_name,
            album_title=row.album_title,
            image_url=row.image_url,
            album_url=row.spotify_url,
            duration_ms=row.duration_ms,
        )


class TopTracksResponse(BaseModel):
    tracks: list[TopTrackItem] = []
