from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from ..core.crypto import decrypt, encrypt


class EncryptedString(TypeDecorator):
    """A Text column whose value is Fernet-encrypted at rest (A4).

    The SQL column stays TEXT (it stores base64 ciphertext), so swapping a column
    to this type is a data-only change — no schema alter. ORM attribute access is
    unchanged: encryption happens on write (bind) and decryption on read (result).
    ``None`` passes through so nullable columns keep working. Used for the Spotify
    token columns, which are never indexed or queried by value.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)
