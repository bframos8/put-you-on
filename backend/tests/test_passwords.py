"""
Password hashing (0.0.1 A2): app/core/passwords.py, and the email-validator pin.

CI runs this suite inside the built backend image, which is what gives the EmailStr test
its teeth: the local venv happens to have email-validator installed by hand, so locally
that test passes with or without the pin, but in the image it fails without it.
"""

import logging

import pytest
from argon2 import PasswordHasher
from pydantic import BaseModel, EmailStr, ValidationError

from app.core.passwords import hash_password, password_needs_rehash, verify_password

PASSWORD = "correct horse battery staple"


class TestHashPassword:
    def test_uses_argon2id_with_the_owasp_parameters(self):
        # The parameters are encoded in the hash itself, so this pins them: 19 MiB,
        # 2 passes, 1 lane. A change to them should be deliberate and visible here.
        assert hash_password(PASSWORD).startswith("$argon2id$v=19$m=19456,t=2,p=1$")

    def test_same_password_hashes_differently_each_time(self):
        # A fresh random salt per hash, so two accounts with the same password don't
        # share a hash.
        assert hash_password(PASSWORD) != hash_password(PASSWORD)


class TestVerifyPassword:
    def test_correct_password_verifies(self):
        assert verify_password(hash_password(PASSWORD), PASSWORD) is True

    def test_wrong_password_does_not_verify_and_logs_nothing(self, caplog):
        # A wrong password is the ordinary case. If it logged at ERROR, every typo
        # would raise a Sentry event.
        password_hash = hash_password(PASSWORD)
        with caplog.at_level(logging.ERROR, logger="app.core.passwords"):
            assert verify_password(password_hash, PASSWORD + "!") is False
        assert caplog.records == []

    def test_canonically_equivalent_forms_match(self):
        # "café" with é as one code point, then as "e" plus a combining accent. Different
        # devices send either.
        composed = "caf\u00e9 au lait"
        decomposed = "cafe\u0301 au lait"
        assert composed != decomposed
        assert verify_password(hash_password(composed), decomposed) is True

    def test_compatibility_forms_match(self):
        # The "fi" ligature (one code point) and the two letters. Only NFKC folds these
        # together; NFC alone would keep them apart, so this is what pins the "K".
        ligature = "\ufb01ne-tuned"
        assert ligature != "fine-tuned"
        assert verify_password(hash_password(ligature), "fine-tuned") is True

    @pytest.mark.parametrize(
        "bad_hash",
        [
            "$argon2id$v=19$m=19456,t=2,p=1$not-a-real-hash",  # parses, can't verify
            "",  # InvalidHashError
            "$2b$12$abcdefghijklmnopqrstuuMIqMjSSgYfu2ZDSvU8mOHqAvzMz7K8e",  # bcrypt
            "$argon2id$v=19$m=19456,t=2,p=1$\u00e9\u00e9",  # non-ASCII: UnicodeEncodeError
        ],
        ids=["unverifiable", "empty", "bcrypt", "non-ascii"],
    )
    def test_bad_stored_hash_fails_closed_and_logs_without_the_hash(self, caplog, bad_hash):
        with caplog.at_level(logging.ERROR, logger="app.core.passwords"):
            assert verify_password(bad_hash, PASSWORD) is False
        assert "could not be checked" in caplog.text
        if bad_hash:
            assert bad_hash not in caplog.text
        assert PASSWORD not in caplog.text

    def test_missing_hash_fails_closed_and_logs(self, caplog):
        # password_hash is nullable: Google and Spotify accounts have none.
        with caplog.at_level(logging.ERROR, logger="app.core.passwords"):
            assert verify_password(None, PASSWORD) is False
        assert "No password hash stored" in caplog.text


class TestNeedsRehash:
    def test_own_hash_does_not_need_rehash(self):
        assert password_needs_rehash(hash_password(PASSWORD)) is False

    def test_hash_with_other_parameters_needs_rehash(self):
        # argon2-cffi's defaults (64 MiB, 3 passes, 4 lanes) differ from ours, which is
        # exactly the situation after the parameters are changed later.
        assert password_needs_rehash(PasswordHasher().hash(PASSWORD)) is True


class TestEmailValidatorInstalled:
    """EmailStr needs the email-validator package, which pydantic does not install."""

    class _Model(BaseModel):
        email: EmailStr

    def test_valid_email_accepted(self):
        assert self._Model(email="a@example.com").email == "a@example.com"

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            self._Model(email="not-an-email")
