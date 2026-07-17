"""encrypt spotify tokens at rest (A4)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-25 00:00:00.000000

A4: the `users.spotify_access_token` / `spotify_refresh_token` columns are now
read through the `EncryptedString` (Fernet) type. The SQL type stays TEXT, so
there is no schema change — only a data migration.

Migration strategy (Option 2 — chosen): discard any existing PLAINTEXT tokens by
nulling the columns. Pre-existing plaintext cannot be Fernet-decrypted, so it
must not survive into the encrypted-read world. Affected users simply
re-authenticate via Spotify on next login (`upsert_user` then writes fresh,
encrypted tokens). On a fresh DB this is a harmless no-op (no rows).

NOTE: export TOKEN_ENCRYPTION_KEYS before running `alembic upgrade head` — the
models import app.core.crypto, which fail-fasts at import without it.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Discard existing plaintext tokens; users re-auth to repopulate (encrypted).
    op.execute(
        "UPDATE users SET spotify_access_token = NULL, spotify_refresh_token = NULL"
    )


def downgrade() -> None:
    # Irreversible: the discarded plaintext tokens cannot be restored. Reverting
    # the encryption itself is done by changing the model columns back to Text.
    pass
