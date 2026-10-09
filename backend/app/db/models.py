import enum
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Enum, ForeignKey, Index, Integer, Text, UniqueConstraint, false, func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from .database import Base
from .types import EncryptedString


class WorkStatus(enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class AuthProvider(enum.Enum):
    email = "email"
    google = "google"
    spotify = "spotify"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    # Nullable since 0.0.1 (migration e5f6a7b8c9d0): email and Google accounts have none.
    spotify_id = Column(Text, unique=True)
    display_name = Column(Text)
    # Always stored lowercase. Email is the identity key from 0.0.1 on, and
    # uq_users_email_lower below makes the database refuse case variants.
    email = Column(Text, unique=True)
    spotify_access_token = Column(EncryptedString)
    spotify_refresh_token = Column(EncryptedString)
    token_expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Google's stable `sub` claim, not the email: it survives the person changing their
    # Google address.
    google_id = Column(Text)
    # argon2id hash, never the password and never EncryptedString (which is reversible).
    password_hash = Column(Text)
    # Which sign-in path owns the account. Server defaults only, no ORM defaults, and
    # both mirror the migration: 'spotify' covers the existing rows and keeps
    # upsert_user (which never sets it) working until the Spotify login is retired. New
    # code sets it explicitly. env.py doesn't set compare_server_default, so the two
    # would drift silently if one changed without the other.
    auth_provider = Column(
        Enum(AuthProvider, name="auth_provider_enum", create_type=False),
        nullable=False,
        server_default=AuthProvider.spotify.value,
    )
    # Ships now, gates nothing yet; email confirmation is a later release.
    email_verified = Column(Boolean, nullable=False, server_default=false())

    # Named, so a later migration never has to guess an auto-generated name. The
    # expression index is compared properly by `alembic check` under SQLAlchemy 2 (Alembic
    # skips expression indexes only when running on SQLAlchemy 1.x), so it is declared here
    # rather than living only in the migration.
    __table_args__ = (
        UniqueConstraint("google_id", name="uq_users_google_id"),
        Index("uq_users_email_lower", func.lower(email), unique=True),
    )

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
    __table_args__ = (UniqueConstraint("url", name="uq_albums_url"),)

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
    __table_args__ = (UniqueConstraint("album_id", "title", name="uq_songs_album_id_title"),)

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
    # One row per (user, track). Spotify's top tracks never repeat, but 0.0.1's picks can
    # (a double click, two tabs), and a duplicate seed would also count twice against the
    # 25-seed cap that 0.0.1 Phase B adds.
    __table_args__ = (
        UniqueConstraint("user_id", "spotify_track_id", name="uq_user_top_songs_user_track"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    song_id = Column(Integer, ForeignKey("songs.id"))
    spotify_track_id = Column(Text, nullable=False)
    spotify_url = Column(Text)
    image_url = Column(Text)
    artist_name = Column(Text)
    track_title = Column(Text)
    album_title = Column(Text)
    duration_ms = Column(Integer)
    genre = Column(Text)
    snapshot_at = Column(DateTime, default=datetime.now)
    used_as_query = Column(Boolean, default=False, nullable=False)

    # Ingest queue state (10.5). A seed whose audio can't be fetched used to stay
    # song_id IS NULL forever, which snapshot_is_stale reads as "rebuild me" — an
    # infinite re-ingest loop. These let a failure become terminal after INGEST_MAX_ATTEMPTS.
    # server_default mirrors the migration: without it the two silently drift, because
    # alembic/env.py doesn't set compare_server_default so autogenerate never compares them.
    ingest_attempts = Column(Integer, default=0, server_default="0", nullable=False)
    # NULL means "still eligible to retry". snapshot_is_stale keys off exactly this.
    ingest_failed_at = Column(DateTime)
    ingest_error = Column(Text)

    # Lease held by the external ingest worker (10.6). Written by Postgres `now()` at
    # claim time and compared only in SQL, so it never has to agree with the clock on the
    # worker's machine. NULL means unclaimed; an expired lease is reclaimable, which is
    # what stops a worker that dies mid-job from parking a row forever.
    claimed_at = Column(DateTime)

    user = relationship("User", back_populates="top_songs")
    song = relationship("Song", back_populates="user_top_songs")


class UserRecommendation(Base):
    __tablename__ = "user_recommendations"
    __table_args__ = (
        Index("ix_user_recommendations_user_date", "user_id", "dispatch_date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    song_id = Column(Integer, ForeignKey("songs.id"), nullable=False)
    query_song_id = Column(Integer, ForeignKey("songs.id"))
    # Queried only as (user_id, dispatch_date), covered by the composite index in
    # __table_args__; no standalone dispatch_date index (it was never on the live DB).
    dispatch_date = Column(Date)
    recommended_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="recommendations")
    song = relationship("Song", foreign_keys=[song_id], back_populates="recommendations")
    query_song = relationship("Song", foreign_keys=[query_song_id])
