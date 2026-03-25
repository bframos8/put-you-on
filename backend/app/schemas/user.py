from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    spotify_id: str
    display_name: str
    email: EmailStr
    spotify_access_token: str
    spotify_refresh_token: str
    token_expires_at: datetime


class UserTokenUpdate(BaseModel):
    spotify_access_token: str
    spotify_refresh_token: str
    token_expires_at: datetime
