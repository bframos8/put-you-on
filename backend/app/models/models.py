import enum
from datetime import datetime
from sqlalchemy import BigInteger, Column, Enum, ForeignKey, Integer, Text, Timestamp
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from ..db.database import Base


class WorkStatus(enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class Artist(Base):
    __tablename__ = "artists"

    id = Column(Integer, primary_key=True)
    bandcamp_band_id = Column(BigInteger, unique=True)
    url = Column(Text)
    band_name = Column(Text)
    band_location = Column(Text)

    albums = relationship("Album", back_populates="artist")


class Album(Base):
    __tablename__ = "albums"

    id = Column(Integer, primary_key=True)
    title = Column(Text, default="Void")
    external_source_id = Column(BigInteger, unique=True)
    source = Column(Text)
    created_at = Column(Timestamp, default=datetime.now)
    updated_at = Column(Timestamp)
    url = Column(Text, default="Void")
    duration = Column(Integer)
    release_date = Column(Text)
    artist_name = Column(Text)
    artist_id = Column(Integer, ForeignKey("artists.id"))
    work_status = Column(Enum(WorkStatus, name="work_status_enum"), default=WorkStatus.pending)
    image_url = Column(Text)

    artist = relationship("Artist", back_populates="albums")
    songs = relationship("Song", back_populates="album")


class Song(Base):
    __tablename__ = "songs"

    id = Column(Integer, primary_key=True)
    title = Column(Text)
    artist_name = Column(Text)
    album_title = Column(Text)
    album_id = Column(Integer, ForeignKey("albums.id"))
    embedding = Column(Vector(1280))
    created_at = Column(Timestamp, default=datetime.now)
    updated_at = Column(Timestamp)

    album = relationship("Album", back_populates="songs")
