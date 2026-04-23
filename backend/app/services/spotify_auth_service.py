import os
import base64
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from ..db.models import User

env_path = Path(__file__).resolve().parents[3] / ".env-backend"
load_dotenv(dotenv_path=env_path)

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/auth/spotify/callback")
SPOTIFY_SCOPES = "user-read-email user-read-private user-top-read"
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyAuthService:
    def _auth_header(self) -> str:
        credentials = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
        return "Basic " + base64.b64encode(credentials.encode()).decode()

    def get_auth_url(self) -> tuple[str, str]:
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "scope": SPOTIFY_SCOPES,
            "state": state,
            "show_dialog": "true",
        }
        return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}", state

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                headers={"Authorization": self._auth_header()},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": SPOTIFY_REDIRECT_URI,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_track_genres(self, tracks: list[dict], access_token: str) -> dict[str, str | None]:
        """Return a mapping of Spotify track_id → canonical genre for each track.

        Batch-fetches artist objects (up to 50 per request) to get Spotify's
        genre tags, then normalizes them to Bandcamp's canonical taxonomy.
        """
        from .genre_normalizer import normalize_genre

        # Build artist_id → [track_ids] map (one artist may appear on many tracks)
        artist_to_tracks: dict[str, list[str]] = {}
        for track in tracks:
            artist_id = track["artists"][0]["id"]
            artist_to_tracks.setdefault(artist_id, []).append(track["id"])

        artist_ids = list(artist_to_tracks.keys())
        artist_genres: dict[str, str | None] = {}

        async with httpx.AsyncClient() as client:
            # Spotify allows up to 50 artist IDs per request
            for i in range(0, len(artist_ids), 50):
                batch = artist_ids[i : i + 50]
                response = await client.get(
                    "https://api.spotify.com/v1/artists",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"ids": ",".join(batch)},
                )
                response.raise_for_status()
                for artist in response.json()["artists"]:
                    artist_genres[artist["id"]] = normalize_genre(artist.get("genres") or [])

        return {
            track["id"]: artist_genres.get(track["artists"][0]["id"])
            for track in tracks
        }

    async def get_top_tracks(self, access_token: str, limit: int = 10) -> list[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me/top/tracks",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json()["items"]

    async def get_spotify_profile(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def upsert_user(self, db: Session, token_data: dict, profile: dict) -> User:
        spotify_id = profile["id"]
        expires_at = datetime.now() + timedelta(seconds=token_data["expires_in"])

        user = db.query(User).filter(User.spotify_id == spotify_id).first()
        if user:
            user.spotify_access_token = token_data["access_token"]
            if "refresh_token" in token_data:
                user.spotify_refresh_token = token_data["refresh_token"]
            user.token_expires_at = expires_at
            user.updated_at = datetime.now()
        else:
            user = User(
                spotify_id=spotify_id,
                display_name=profile.get("display_name"),
                email=profile.get("email"),
                spotify_access_token=token_data["access_token"],
                spotify_refresh_token=token_data["refresh_token"],
                token_expires_at=expires_at,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(user)

        db.commit()
        db.refresh(user)
        return user

    async def refresh_tokens(self, db: Session, user: User) -> User:
        if user.token_expires_at > datetime.now():
            return user

        async with httpx.AsyncClient() as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                headers={"Authorization": self._auth_header()},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": user.spotify_refresh_token,
                },
            )
            response.raise_for_status()
            data = response.json()

        user.spotify_access_token = data["access_token"]
        if "refresh_token" in data:
            user.spotify_refresh_token = data["refresh_token"]
        user.token_expires_at = datetime.now() + timedelta(seconds=data["expires_in"])
        user.updated_at = datetime.now()
        db.commit()
        db.refresh(user)
        return user
