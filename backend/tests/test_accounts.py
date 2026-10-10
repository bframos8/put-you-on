"""
The one-path rule (0.0.1 A3): app/core/accounts.py.

Rows are real, unsaved `User` objects with the provider set explicitly, and the session
is a MagicMock specced to Session, built here rather than taken from conftest. Two
reasons: auth_provider and email_verified have server defaults only, so a `User` built
without them reads None (conftest's mock_user does), which would quietly mean "no
account" to the rule; and a plain MagicMock row's attributes are MagicMocks, which equal
nothing and would hide a wrong comparison.
"""

from unittest.mock import MagicMock

import logging

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.accounts import Decision, ProviderConflict, decide, normalize_email, resolve_user
from app.db.models import AuthProvider, User

EMAIL, GOOGLE, SPOTIFY = AuthProvider.email, AuthProvider.google, AuthProvider.spotify

USE_GOOGLE_FROM_GOOGLE = "An account with this email already exists. Continue with Google to sign in."
USE_GOOGLE_FROM_SPOTIFY = "This account was created with Spotify. Sign in with Google using the same email."
USE_PASSWORD = "An account with this email already exists. Sign in with your password."
GOOGLE_MISMATCH = "This email is already linked to a different Google account."

_COLUMNS = (
    "email", "display_name", "spotify_id", "spotify_access_token", "spotify_refresh_token",
    "google_id", "password_hash", "auth_provider", "email_verified",
)


def _user(provider, **kwargs) -> User:
    kwargs.setdefault("id", 1)
    kwargs.setdefault("email", "foo.bar@example.com")
    kwargs.setdefault("email_verified", False)
    return User(auth_provider=provider, **kwargs)


def _snapshot(user: User) -> dict:
    return {c: getattr(user, c) for c in _COLUMNS}


def _db(row) -> MagicMock:
    db = MagicMock(spec=Session)
    db.query.return_value.filter.return_value.first.return_value = row
    return db


def _compiled_filter(db) -> str:
    expr = db.query.return_value.filter.call_args.args[0]
    return str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class TestNormalizeEmail:
    def test_strips_and_lowercases_the_whole_address(self):
        # EmailStr keeps the local part's case ("Foo.Bar@example.com"), so this has to
        # lowercase all of it.
        assert normalize_email("  Foo.Bar@Example.COM ") == "foo.bar@example.com"


class TestDecide:
    @pytest.mark.parametrize(
        "owner, attempted, expected",
        [
            (None, EMAIL, Decision.create),
            (EMAIL, EMAIL, Decision.existing),
            (None, GOOGLE, Decision.create),
            (GOOGLE, GOOGLE, Decision.existing),
            (SPOTIFY, GOOGLE, Decision.link),
        ],
    )
    def test_allowed(self, owner, attempted, expected):
        assert decide(owner, attempted) is expected

    @pytest.mark.parametrize(
        "owner, attempted, message, code",
        [
            (GOOGLE, EMAIL, USE_GOOGLE_FROM_GOOGLE, "use_google"),
            (SPOTIFY, EMAIL, USE_GOOGLE_FROM_SPOTIFY, "use_google"),
            (EMAIL, GOOGLE, USE_PASSWORD, "use_password"),
        ],
    )
    def test_conflicts_name_the_right_way_in(self, owner, attempted, message, code):
        with pytest.raises(ProviderConflict) as exc:
            decide(owner, attempted)
        assert (exc.value.owner, exc.value.message, exc.value.code) == (owner, message, code)
        assert str(exc.value) == message

    @pytest.mark.parametrize("owner", [None, EMAIL, GOOGLE, SPOTIFY])
    def test_spotify_is_never_an_attempted_provider(self, owner):
        # The Spotify login keeps using upsert_user until Phase D.
        with pytest.raises(ValueError):
            decide(owner, SPOTIFY)

    @pytest.mark.parametrize("owner", ["google", MagicMock()])
    def test_an_owner_that_is_not_a_provider_is_an_error(self, owner):
        with pytest.raises(ValueError):
            decide(owner, EMAIL)


class TestResolveUser:
    def test_no_account_returns_none_and_looks_up_case_insensitively(self):
        db = _db(None)
        assert resolve_user(db, "Foo.Bar@Example.COM", EMAIL) is None
        # lower(email) on the column matches the uq_users_email_lower index, and the
        # value is normalized, so a mixed-case sign-in finds its own account.
        assert _compiled_filter(db) == "lower(users.email) = 'foo.bar@example.com'"
        db.commit.assert_not_called()
        db.add.assert_not_called()

    def test_no_account_still_refuses_a_spotify_attempt(self):
        with pytest.raises(ValueError):
            resolve_user(_db(None), "foo.bar@example.com", SPOTIFY)

    def test_same_provider_returns_the_account_unchanged(self):
        row = _user(EMAIL, password_hash="hash")
        before = _snapshot(row)
        db = _db(row)
        assert resolve_user(db, "foo.bar@example.com", EMAIL) is row
        assert _snapshot(row) == before
        db.commit.assert_not_called()
        db.add.assert_not_called()

    def test_conflict_raises_changes_nothing_and_logs_nothing(self, caplog):
        # An ordinary conflict ("use your password") is a person picking the wrong
        # button, not something to log.
        row = _user(GOOGLE, google_id="sub-1")
        before = _snapshot(row)
        db = _db(row)
        with caplog.at_level(logging.DEBUG, logger="app.core.accounts"):
            with pytest.raises(ProviderConflict) as exc:
                resolve_user(db, "foo.bar@example.com", EMAIL)
        assert caplog.records == []
        assert (exc.value.owner, exc.value.message, exc.value.code) == (
            GOOGLE, USE_GOOGLE_FROM_GOOGLE, "use_google"
        )
        assert _snapshot(row) == before
        db.commit.assert_not_called()
        db.add.assert_not_called()

    def test_google_with_the_same_sub_returns_the_account(self):
        row = _user(GOOGLE, google_id="sub-1")
        before = _snapshot(row)
        db = _db(row)
        assert resolve_user(db, "foo.bar@example.com", GOOGLE, google_sub="sub-1") is row
        assert _snapshot(row) == before
        db.commit.assert_not_called()

    def test_google_with_a_different_sub_is_refused_and_logged(self, caplog):
        # The address now belongs to a different Google account. Signing it in would
        # hand over the old account.
        row = _user(GOOGLE, id=42, google_id="sub-1")
        before = _snapshot(row)
        db = _db(row)
        with caplog.at_level(logging.WARNING, logger="app.core.accounts"):
            with pytest.raises(ProviderConflict) as exc:
                resolve_user(db, "foo.bar@example.com", GOOGLE, google_sub="sub-2")
        [record] = caplog.records
        assert record.levelno == logging.WARNING
        assert "account 42" in record.getMessage()
        assert record.args == (42,)  # %s formatting: Sentry groups on the raw message
        for private in ("foo.bar@example.com", "sub-1", "sub-2"):
            assert private not in caplog.text
        assert (exc.value.owner, exc.value.message, exc.value.code) == (
            GOOGLE, GOOGLE_MISMATCH, "google_mismatch"
        )
        assert _snapshot(row) == before
        db.commit.assert_not_called()

    def test_google_without_a_sub_is_an_error_before_any_lookup(self):
        db = _db(_user(GOOGLE, google_id="sub-1"))
        with pytest.raises(ValueError):
            resolve_user(db, "foo.bar@example.com", GOOGLE)
        db.query.assert_not_called()

    def test_an_account_without_a_provider_is_an_error_not_a_create(self):
        # None means "no account" to decide(); an existing row must never reach it as
        # None. Only an unsaved row can look like this: the column is NOT NULL.
        row = _user(None)
        db = _db(row)
        with pytest.raises(ValueError):
            resolve_user(db, "foo.bar@example.com", EMAIL)
        db.commit.assert_not_called()

    def test_spotify_account_signing_in_with_google_is_linked(self):
        row = _user(
            SPOTIFY,
            spotify_id="sp-1",
            display_name="One",
            spotify_access_token="access",
            spotify_refresh_token="refresh",
        )
        before = _snapshot(row)
        db = _db(row)
        assert resolve_user(db, "Foo.Bar@Example.COM", GOOGLE, google_sub="sub-9") is row

        assert (row.google_id, row.auth_provider, row.email_verified) == ("sub-9", GOOGLE, True)
        # Everything else stays as it was, the Spotify columns included (dormant).
        changed = {"google_id", "auth_provider", "email_verified"}
        assert {c: v for c, v in _snapshot(row).items() if c not in changed} == {
            c: v for c, v in before.items() if c not in changed
        }
        assert row.password_hash is None
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(row)
        db.add.assert_not_called()
