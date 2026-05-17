"""PHI field encryption — AES-256-GCM.

Envelope format stored as a string:
    enc:v1:<base64(key_id_byte || nonce_12 || tag_16 || ciphertext)>

The leading key_id byte enables key rotation: old envelopes decrypt with their
original key; new encryptions always use the current key.
"""

import base64
import os
from abc import ABC, abstractmethod

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as exc:  # pragma: no cover
    raise ImportError("cryptography package is required for PHI encryption") from exc

_PREFIX = "enc:v1:"


class KeyProvider(ABC):
    @abstractmethod
    def get_key(self, key_id: int) -> bytes: ...

    @abstractmethod
    def current_key_id(self) -> int: ...


class EnvKeyProvider(KeyProvider):
    """Single-key provider backed by a hex-encoded 32-byte secret."""

    def __init__(self, master_key_hex: str) -> None:
        raw = bytes.fromhex(master_key_hex)
        if len(raw) != 32:  # pragma: no cover
            raise ValueError("PHI_MASTER_KEY must be 32 bytes (64 hex chars)")
        self._keys: dict[int, bytes] = {0: raw}

    def get_key(self, key_id: int) -> bytes:
        try:
            return self._keys[key_id]
        except KeyError as exc:
            raise ValueError(f"Unknown PHI key_id: {key_id}") from exc

    def current_key_id(self) -> int:
        return max(self._keys)


class PhiCipher:
    """Encrypt/decrypt individual PHI string values."""

    def __init__(self, provider: KeyProvider) -> None:
        self._provider = provider

    def encrypt(self, plaintext: str) -> str:
        key_id = self._provider.current_key_id()
        key = self._provider.get_key(key_id)
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        # encrypt() appends the 16-byte GCM tag to the ciphertext
        ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
        payload = bytes([key_id]) + nonce + ct_with_tag
        return _PREFIX + base64.b64encode(payload).decode()

    def decrypt(self, envelope: str) -> str:
        if not envelope.startswith(_PREFIX):
            raise ValueError("Value is not an encrypted PHI envelope")
        payload = base64.b64decode(envelope[len(_PREFIX) :])
        key_id = payload[0]
        nonce = payload[1:13]
        ct_with_tag = payload[13:]
        key = self._provider.get_key(key_id)
        aesgcm = AESGCM(key)
        plaintext_bytes = aesgcm.decrypt(nonce, ct_with_tag, None)
        return plaintext_bytes.decode()

    @staticmethod
    def is_encrypted(value: str) -> bool:
        return value.startswith(_PREFIX)
