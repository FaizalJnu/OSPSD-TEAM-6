"""Encrypting provider tokens before they reach the database.

Provider tokens must be recovered to call the provider, so they are encrypted,
not hashed. The key comes from ``CONNECTION_TOKEN_KEY`` in the API service's
environment and is never stored with the ciphertext: a copy of the database or a
backup alone reveals no token.

Fernet (AES-128-CBC with HMAC-SHA256) authenticates every ciphertext, so a
changed one fails to decrypt instead of decrypting to something else. Each value
is sealed together with a context, such as ``<user ID>:trello:access_token``, and
opening checks it, so a ciphertext copied into another user's row or another
column cannot be used there.

``CONNECTION_TOKEN_KEY`` holds one key, or several separated by commas to rotate:
the first encrypts, and any of them decrypts.
"""

import json
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from meeting_prep.config import ConfigError, require

KEY_SETTING = "CONNECTION_TOKEN_KEY"


class TokenUnreadable(Exception):
    """A stored token could not be decrypted: wrong key, changed data, or the wrong row."""


class TokenCipher:
    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ConfigError(f"{KEY_SETTING} is not set")
        try:
            self._fernet = MultiFernet([Fernet(key) for key in keys])
        except ValueError, TypeError:
            raise ConfigError(
                f"{KEY_SETTING} must hold Fernet keys (32 url-safe base64-encoded bytes)"
            ) from None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> TokenCipher:
        """Read the keys from ``CONNECTION_TOKEN_KEY``. Errors name the setting, never a key."""
        raw = require(env, KEY_SETTING)
        return cls([key.strip() for key in raw.split(",") if key.strip()])

    @staticmethod
    def new_key() -> str:
        """A fresh key, for ``.env`` or a deployment secret."""
        return Fernet.generate_key().decode("ascii")

    def seal(self, value: str, *, context: str) -> str:
        payload = json.dumps({"context": context, "value": value}, separators=(",", ":"))
        return self._fernet.encrypt(payload.encode("utf-8")).decode("ascii")

    def open(self, sealed: str, *, context: str) -> str:
        try:
            payload = json.loads(self._fernet.decrypt(sealed.encode("ascii")))
        except InvalidToken, ValueError:
            raise TokenUnreadable() from None
        if not isinstance(payload, dict) or payload.get("context") != context:
            raise TokenUnreadable()
        value = payload.get("value")
        if not isinstance(value, str):
            raise TokenUnreadable()
        return value
