"""A4 — Spotify token encryption at rest (app-level Fernet)."""
import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    create_engine,
    select,
    text,
)

from app.core.crypto import decrypt, encrypt
from app.db.types import EncryptedString

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_encrypt_decrypt_roundtrip():
    assert decrypt(encrypt("a-spotify-token")) == "a-spotify-token"


def test_ciphertext_is_not_plaintext():
    assert encrypt("a-spotify-token") != "a-spotify-token"


def test_multifernet_rotation_property():
    # The rotation design relies on MultiFernet: encrypt with the first key,
    # decrypt with any. Encrypt under an old key, then decrypt after a new key is
    # prepended (old kept) — must still resolve.
    old, new = Fernet.generate_key(), Fernet.generate_key()
    token = MultiFernet([Fernet(old)]).encrypt(b"rotate-me")
    assert MultiFernet([Fernet(new), Fernet(old)]).decrypt(token) == b"rotate-me"


def test_missing_key_fails_fast():
    # app.core.crypto must raise at IMPORT time if TOKEN_ENCRYPTION_KEYS is unset.
    env = {k: v for k, v in os.environ.items() if k != "TOKEN_ENCRYPTION_KEYS"}
    env["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.crypto"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "TOKEN_ENCRYPTION_KEYS" in result.stderr


def test_encrypted_string_none_passthrough():
    col = EncryptedString()
    assert col.process_bind_param(None, None) is None
    assert col.process_result_value(None, None) is None


def test_encrypted_string_roundtrips_and_is_ciphertext_at_rest():
    # Exercise the type against a real engine with a minimal table (NOT
    # Base.metadata — it carries a pgvector column that won't create under sqlite).
    engine = create_engine("sqlite://")
    md = MetaData()
    tbl = Table(
        "secrets",
        md,
        Column("id", Integer, primary_key=True),
        Column("secret", EncryptedString),
    )
    md.create_all(engine)
    with engine.begin() as conn:
        conn.execute(tbl.insert().values(id=1, secret="a-spotify-token"))
    with engine.connect() as conn:
        # Reading through the typed column transparently decrypts.
        assert conn.execute(select(tbl.c.secret)).scalar_one() == "a-spotify-token"
        # The value actually stored is ciphertext (and is valid Fernet).
        raw = conn.execute(text("SELECT secret FROM secrets")).scalar_one()
        assert raw != "a-spotify-token"
        assert decrypt(raw) == "a-spotify-token"
