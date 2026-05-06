"""Tests for app.core.crypto — AES-256-GCM PHI encryption."""

import pytest

from app.core.crypto import EnvKeyProvider, PhiCipher

_KEY = "a" * 64  # 32 bytes of 0xaa


@pytest.fixture
def cipher() -> PhiCipher:
    return PhiCipher(EnvKeyProvider(_KEY))


def test_round_trip(cipher: PhiCipher) -> None:
    plaintext = "John Smith"
    envelope = cipher.encrypt(plaintext)
    assert PhiCipher.is_encrypted(envelope)
    assert cipher.decrypt(envelope) == plaintext


def test_round_trip_empty_string(cipher: PhiCipher) -> None:
    assert cipher.decrypt(cipher.encrypt("")) == ""


def test_round_trip_long_value(cipher: PhiCipher) -> None:
    long_text = "A" * 512
    assert cipher.decrypt(cipher.encrypt(long_text)) == long_text


def test_each_encrypt_produces_unique_envelope(cipher: PhiCipher) -> None:
    """Different nonces → different ciphertexts even for the same plaintext."""
    e1 = cipher.encrypt("same")
    e2 = cipher.encrypt("same")
    assert e1 != e2


def test_tampered_ciphertext_rejected(cipher: PhiCipher) -> None:
    import base64

    envelope = cipher.encrypt("secret")
    prefix = "enc:v1:"
    payload = bytearray(base64.b64decode(envelope[len(prefix):]))
    payload[-1] ^= 0xFF  # flip last byte of tag
    tampered = prefix + base64.b64encode(bytes(payload)).decode()
    with pytest.raises(Exception):  # cryptography raises InvalidTag
        cipher.decrypt(tampered)


def test_tampered_nonce_rejected(cipher: PhiCipher) -> None:
    import base64

    envelope = cipher.encrypt("secret")
    prefix = "enc:v1:"
    payload = bytearray(base64.b64decode(envelope[len(prefix):]))
    payload[5] ^= 0x01  # flip a nonce byte
    tampered = prefix + base64.b64encode(bytes(payload)).decode()
    with pytest.raises(Exception):
        cipher.decrypt(tampered)


def test_decrypt_not_encrypted_raises(cipher: PhiCipher) -> None:
    with pytest.raises(ValueError, match="not an encrypted"):
        cipher.decrypt("plaintext_not_encrypted")


def test_unknown_key_id_raises() -> None:
    provider = EnvKeyProvider(_KEY)
    with pytest.raises(ValueError, match="Unknown PHI key_id"):
        provider.get_key(99)


def test_is_encrypted_false_for_plaintext() -> None:
    assert not PhiCipher.is_encrypted("John Smith")
    assert not PhiCipher.is_encrypted("")
    assert not PhiCipher.is_encrypted("enc:v2:something")


def test_is_encrypted_true_for_envelope(cipher: PhiCipher) -> None:
    assert PhiCipher.is_encrypted(cipher.encrypt("x"))


def test_invalid_master_key_length() -> None:
    with pytest.raises(ValueError):
        EnvKeyProvider("tooshort")


def test_invalid_master_key_not_hex() -> None:
    with pytest.raises(ValueError):
        EnvKeyProvider("z" * 64)


def test_key_rotation_old_envelope_still_decrypts() -> None:
    """After adding key 1, envelopes encrypted under key 0 still decrypt."""
    provider = EnvKeyProvider(_KEY)
    cipher_v0 = PhiCipher(provider)
    envelope_v0 = cipher_v0.encrypt("old data")

    # Simulate adding a new key
    new_key = "b" * 64
    provider._keys[1] = bytes.fromhex(new_key)

    # Current ID advances to 1
    assert provider.current_key_id() == 1

    # New encryptions use key 1
    cipher_v1 = PhiCipher(provider)
    envelope_v1 = cipher_v1.encrypt("new data")
    assert cipher_v1.decrypt(envelope_v0) == "old data"
    assert cipher_v1.decrypt(envelope_v1) == "new data"
