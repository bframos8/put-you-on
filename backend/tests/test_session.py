"""
Unit tests for app/core/session.py.

These tests run without the HTTP layer — they call create_session /
decode_session directly and verify the itsdangerous contract.
"""

import time
from unittest.mock import patch

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.core.session import (
    SESSION_MAX_AGE,
    SESSION_SECRET,
    create_session,
    decode_session,
)


class TestCreateSession:
    def test_returns_a_string(self):
        assert isinstance(create_session(1), str)

    def test_returns_non_empty_string(self):
        assert len(create_session(1)) > 0

    def test_different_user_ids_produce_different_tokens(self):
        assert create_session(1) != create_session(2)

    def test_token_encodes_the_user_id(self):
        for uid in [1, 42, 9999]:
            assert decode_session(create_session(uid)) == uid

    def test_large_user_id_is_handled(self):
        assert decode_session(create_session(2**31 - 1)) == 2**31 - 1

    def test_user_id_zero_is_handled(self):
        # Edge: user_id=0 is unusual but shouldn't crash
        assert decode_session(create_session(0)) == 0


class TestDecodeSession:
    # ── valid tokens ──────────────────────────────────────────────────────────

    def test_valid_token_returns_correct_user_id(self):
        token = create_session(7)
        assert decode_session(token) == 7

    def test_roundtrip_preserves_user_id(self):
        for uid in [1, 100, 50000]:
            assert decode_session(create_session(uid)) == uid

    # ── bad / malformed tokens ────────────────────────────────────────────────

    def test_garbage_string_returns_none(self):
        assert decode_session("not.a.real.token") is None

    def test_empty_string_returns_none(self):
        assert decode_session("") is None

    def test_whitespace_returns_none(self):
        assert decode_session("   ") is None

    def test_truncated_token_returns_none(self):
        token = create_session(1)
        assert decode_session(token[:10]) is None

    def test_corrupted_signature_returns_none(self):
        token = create_session(1)
        parts = token.rsplit(".", 1)
        corrupted = parts[0] + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        assert decode_session(corrupted) is None

    def test_modified_payload_returns_none(self):
        """Changing the payload portion invalidates the signature."""
        token = create_session(1)
        # tokens have format  <payload>.<signature>
        # flip a char in the payload
        payload, sig = token.rsplit(".", 1)
        flipped = ("Z" if payload[0] != "Z" else "A") + payload[1:]
        assert decode_session(f"{flipped}.{sig}") is None

    # ── wrong secret / salt ───────────────────────────────────────────────────

    def test_token_signed_with_wrong_secret_returns_none(self):
        bad = URLSafeTimedSerializer("completely-different-secret").dumps(1, salt="session")
        assert decode_session(bad) is None

    def test_token_signed_with_wrong_salt_returns_none(self):
        token = URLSafeTimedSerializer(SESSION_SECRET).dumps(1, salt="not-the-session-salt")
        assert decode_session(token) is None

    # ── expiry ────────────────────────────────────────────────────────────────

    def test_expired_token_returns_none(self):
        """
        Sign a token with a timestamp that is older than SESSION_MAX_AGE.
        We patch itsdangerous.timed.time so the serializer believes the token
        was created in the distant past.
        """
        expired_at = time.time() - SESSION_MAX_AGE - 60  # 1 minute past expiry
        serializer = URLSafeTimedSerializer(SESSION_SECRET)

        with patch("itsdangerous.timed.time") as mock_time:
            mock_time.return_value = expired_at
            expired_token = serializer.dumps(99, salt="session")

        assert decode_session(expired_token) is None

    def test_just_fresh_token_is_valid(self):
        """Token created right now should decode fine."""
        token = create_session(55)
        assert decode_session(token) == 55
