"""Password hashing for email + password accounts (Put You On 0.0.1, A2).

argon2id, a one-way key derivation function. Never `EncryptedString` (app/db/types.py),
which is reversible by design because it exists to give API tokens back. A password is
never logged, and neither is its hash: a hash in a log is an offline guessing target.

**Parameters: OWASP's argon2id profile, not argon2-cffi's defaults.** The library default
is RFC 9106's low-memory profile at 64 MiB per hash. This backend runs under a 1200 MB
container limit on a 2 GB instance and idles around 365 MB, most of that the model
loaded at startup. At 64 MiB, ten logins hashing at the same moment would need about
640 MB, and nothing caps how many arrive at once (the login rate limit is IP-keyed, and
the client IP can currently be spoofed; see deployment-deferred.md). OWASP's minimum
recommended argon2id configuration (19 MiB, 2 passes, 1 lane) is about a third of the
memory per hash. The real ceiling is the threadpool these calls run in (see below):
anyio allows 40 threads by default and there is one uvicorn worker, so at most 40
hashes run at once, about 760 MiB on top of the ~365 MB idle, just under the limit.
`password_needs_rehash` lets the parameters be raised later: A5 rehashes on the next
successful login, with no forced resets.

**Every password is NFKC-normalized before it is hashed or checked.** The same word can
reach us as different code points depending on the device: "é" as one character, or as
"e" followed by a combining accent. Without normalization those are different passwords
and the person is locked out on their other device. NIST SP 800-63B suggests NFKC or
NFKD for exactly this.

**These calls are slow on purpose**, tens of milliseconds of CPU each. Call them from a
sync route (FastAPI runs those in a threadpool) or through `run_in_threadpool`, never
directly inside an `async def` route, or every other request waits behind the hash.
"""
import logging
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

logger = logging.getLogger(__name__)

# The account policy, enforced by the request schemas (0.0.1 A5), which count characters
# as submitted, before normalization. NFKC can change the length a little either way
# (a ligature expands, a combining accent folds in); that is harmless, since argon2
# pre-hashes its input and 128 characters stay small after normalizing. No composition
# rules (digits, symbols): length is what makes a password hard to guess, and
# composition rules mostly produce "Password1!".
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# OWASP's minimum recommended argon2id configuration; see the module docstring for why
# not the library default.
# memory_cost is in KiB: 19456 KiB is 19 MiB. Salt and hash lengths stay at the library
# defaults (16 and 32 bytes), and the type stays argon2id.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def _normalize(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    """Return an argon2id hash of `password`, with a fresh random salt each time."""
    return _hasher.hash(_normalize(password))


def verify_password(password_hash: str | None, password: str) -> bool:
    """True if `password` matches `password_hash`.

    A wrong password is the ordinary case and returns False quietly. Everything else
    returns False too, so login fails closed rather than with a 500, but is logged at
    ERROR, because each one means a row holds something hash_password never wrote and
    Sentry should hear about it:

    - no hash at all. `users.password_hash` is nullable (Google and Spotify accounts have
      none), so this is reachable if a caller skips the provider check;
    - a hash that can't be parsed (InvalidHashError, a ValueError) or contains non-ASCII
      characters (UnicodeEncodeError, also a ValueError). Catching ValueError rather than
      letting either escape matters for more than the 500: Sentry captures local
      variables with an unhandled exception, and its scrubber removes `password` but not
      `password_hash`;
    - a parseable hash argon2 still can't check (VerificationError).

    Only the exception type is logged, never the hash.
    """
    if password_hash is None:
        logger.error("No password hash stored for an account being checked")
        return False
    try:
        return _hasher.verify(password_hash, _normalize(password))
    except VerifyMismatchError:
        return False
    except (ValueError, VerificationError) as e:
        logger.error("Stored password hash could not be checked: %s", type(e).__name__)
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True if `password_hash` was made with parameters other than the current ones.

    For the login endpoint to call after a successful verify, while it still has the
    plain password, so stored hashes follow any later change to the parameters above.
    """
    return _hasher.check_needs_rehash(password_hash)
