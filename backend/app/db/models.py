import enum
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from .database import Base


class WorkStatus(enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    spotify_id = Column(Text, unique=True, nullable=False)
    display_name = Column(Text)
    email = Column(Text, unique=True)
    spotify_access_token = Column(Text)
    spotify_refresh_token = Column(Text)
    token_expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    top_songs = relationship("UserTopSong", back_populates="user")
    recommendations = relationship("UserRecommendation", back_populates="user")


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
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime)
    url = Column(Text, default="Void")
    duration = Column(Integer)
    release_date = Column(Text)
    artist_name = Column(Text)
    artist_id = Column(Integer, ForeignKey("artists.id"))
    work_status = Column(Enum(WorkStatus, name="work_status_enum", create_type=False), default=WorkStatus.pending)
    image_url = Column(Text)
    genre = Column(Text)

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
    is_candidate = Column(Boolean, default=True, nullable=False)
    spotify_track_id = Column(Text, unique=True)
    genre = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime)

    album = relationship("Album", back_populates="songs")
    user_top_songs = relationship("UserTopSong", back_populates="song")
    recommendations = relationship(
        "UserRecommendation",
        foreign_keys="[UserRecommendation.song_id]",
        back_populates="song",
    )


class UserTopSong(Base):
    __tablename__ = "user_top_songs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    song_id = Column(Integer, ForeignKey("songs.id"))
    spotify_track_id = Column(Text, nullable=False)
    spotify_url = Column(Text)
    image_url = Column(Text)
    artist_name = Column(Text)
    track_title = Column(Text)
    album_title = Column(Text)
    genre = Column(Text)
    snapshot_at = Column(DateTime, default=datetime.now)
    used_as_query = Column(Boolean, default=False, nullable=False)

    user = relationship("User", back_populates="top_songs")
    song = relationship("Song", back_populates="user_top_songs")


class UserRecommendation(Base):
    __tablename__ = "user_recommendations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    song_id = Column(Integer, ForeignKey("songs.id"), nullable=False)
    query_song_id = Column(Integer, ForeignKey("songs.id"))
    dispatch_date = Column(Date, index=True)
    recommended_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="recommendations")
    song = relationship("Song", foreign_keys=[song_id], back_populates="recommendations")
    query_song = relationship("Song", foreign_keys=[query_song_id])
