"""Which account a sign-in belongs to: the one-path rule (Put You On 0.0.1, A3).

From 0.0.1 on, an email address is the identity key and belongs to exactly one way of
signing in: a password, Google, or (for the two accounts that predate 0.0.1) Spotify.
Signing in another way gets a message that names the right one. Register, password login
and the Google callback all call `resolve_user`, so the rule is enforced in one place
instead of three call sites drifting apart, and the messages live next to the rules that
produce them.

Known tradeoff: a conflict message confirms that an email is registered. Accepted for
usability, as most consumer apps do.

Spotify is never the *attempted* provider here. Until the Spotify login is retired
(0.0.1 Phase D) it keeps using `SpotifyAuthService.upsert_user`, which keys on the
Spotify id, so a `spotify` row only ever appears as the owner. A Google sign-in that
lands on one links onto it: that is how the pre-0.0.1 accounts get back in once their
session cookies expire.
"""
import enum
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db.models import AuthProvider, User

logger = logging.getLogger(__name__)


class Decision(enum.Enum):
    create = "create"      # no account has this email; the caller may create one
    existing = "existing"  # the account already belongs to this way of signing in
    link = "link"          # a Spotify account, now signing in with Google


class ProviderConflict(Exception):
    """The email belongs to a different way of signing in.

    `message` is shown to the person as written. `code` is the short form for the Google
    callback, which can only redirect with `?error=<code>`. `owner` is the provider that
    owns the account.
    """

    def __init__(self, owner: AuthProvider, message: str, code: str):
        super().__init__(message)
        self.owner = owner
        self.message = message
        self.code = code


def normalize_email(email: str) -> str:
    """Strip and lowercase, which is how every email is stored (migration e5f6a7b8c9d0).

    Needed even after pydantic's EmailStr, which lowercases only the domain and keeps the
    local part's case, and for the Google callback, whose email never passes through
    EmailStr at all. `lower`, not `casefold`: casefold turns "ß" into "ss", which would
    merge two different addresses, and Postgres's lower() does not do it either.
    """
    return email.strip().lower()


def decide(owner: AuthProvider | None, attempted: AuthProvider) -> Decision:
    """The one-path rule on its own, with no database.

    `owner` is the provider of the account that already has this email, or None when no
    account does. Every branch ends in a return or a raise; anything not listed (an
    owner that isn't an AuthProvider, a Spotify attempt) is an error rather than a
    default, so a mistake can never come out as "create".
    """
    if attempted is AuthProvider.email:
        if owner is None:
            return Decision.create
        if owner is AuthProvider.email:
            return Decision.existing
        if owner is AuthProvider.google:
            raise ProviderConflict(
                owner,
                "An account with this email already exists. Continue with Google to sign in.",
                "use_google",
            )
        if owner is AuthProvider.spotify:
            raise ProviderConflict(
                owner,
                "This account was created with Spotify. Sign in with Google using the same email.",
                "use_google",
            )
    elif attempted is AuthProvider.google:
        if owner is None:
            return Decision.create
        if owner is AuthProvider.email:
            raise ProviderConflict(
                owner,
                "An account with this email already exists. Sign in with your password.",
                "use_password",
            )
        if owner is AuthProvider.google:
            return Decision.existing
        if owner is AuthProvider.spotify:
            return Decision.link
    else:
        raise ValueError(f"The one-path rule doesn't handle {attempted!r} sign-ins")
    raise ValueError(f"Account has an unknown provider: {owner!r}")


def resolve_user(
    db: Session, email: str, provider: AuthProvider, google_sub: str | None = None
) -> User | None:
    """Return the account this sign-in belongs to, or None if the caller may create one.

    Raises ProviderConflict when the email belongs to a different way of signing in.

    None is a statement about this moment, not a reservation: a sign-up for the same
    address can still land between this lookup and the caller's insert. The unique
    constraints on email turn that into an IntegrityError at the insert: `users_email_key`
    for the same spelling (the usual case, since every caller normalizes) or
    `uq_users_email_lower` for a case variant. The caller must then roll back (the
    session is unusable until it does), must never log the error (its text contains the
    address), and answers "already exists" rather than a 500. A Google create can also
    hit `uq_users_google_id`; there the winner is most likely the same person in another
    tab, so resolving again is the better answer.

    For a Google sign-in, `google_sub` (the ID token's `sub`) is required, and the caller
    must already have:

    - checked that Google says the email is verified. Linking a Spotify account trusts
      that, and an unverified address would let anyone claim someone else's account;
    - looked the account up by `google_id` and found nothing. That lookup comes first
      because `sub` survives the person changing their Google email. It also means a
      Google-owned account reached here by email is tied to a *different* Google account,
      which is why a mismatched `google_id` is refused below rather than signed in: an
      address can be reassigned to a new Google account, and keying on email alone would
      hand the old account to whoever holds the address now.

    A link (a Spotify account signing in with Google) is committed here rather than left
    to the caller: `get_db` never commits, so a link the caller forgot to commit would
    vanish silently. The Spotify columns are left in place, dormant.
    """
    if provider is AuthProvider.google and not google_sub:
        raise ValueError("A Google sign-in needs the ID token's sub")

    user = db.query(User).filter(func.lower(User.email) == normalize_email(email)).first()
    if user is None:
        decide(None, provider)  # still refuses a provider the rule doesn't handle
        return None

    decision = decide(user.auth_provider, provider)
    if decision is Decision.existing:
        if provider is AuthProvider.google and user.google_id != google_sub:
            # Reaching here takes a Google account that Google says holds this verified
            # address, so this is an address that has moved to another Google account.
            # Worth seeing, but WARNING, not ERROR: ERROR would open a Sentry event on
            # every retry. The account id only; never the email or either sub.
            logger.warning(
                "Refused a Google sign-in for account %s: a different Google account holds that email",
                user.id,
            )
            raise ProviderConflict(
                user.auth_provider,
                "This email is already linked to a different Google account.",
                "google_mismatch",
            )
        return user
    if decision is Decision.link:
        user.google_id = google_sub
        user.auth_provider = AuthProvider.google
        user.email_verified = True
        db.commit()
        db.refresh(user)
        return user
    # Only `create` reaches here, and an existing account can't be created. That happens
    # when the row's provider reads None, which decide() takes to mean "no account":
    # auth_provider is NOT NULL in the database, so it is a row that was never saved,
    # such as one built in a test without the column set. An error, never a None that
    # the caller would read as "go ahead and create".
    raise ValueError(f"Account {user.id} has no provider; refusing to treat it as new")
