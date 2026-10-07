import base64
import hashlib
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import Settings
from backend.core.pin_security import decrypt_pin, encrypt_pin, hash_pin
from backend.core import pin_security


def test_temporary_pin_ciphertext_and_door_binding() -> None:
    plaintext = "0042"
    encrypted = encrypt_pin("Puerta Lobby", plaintext)
    assert plaintext not in encrypted
    assert decrypt_pin("Puerta Lobby", encrypted) == plaintext
    assert hash_pin("Puerta Lobby", plaintext) == hash_pin("Puerta Lobby", plaintext)
    assert hash_pin("Puerta Lobby", plaintext) != hash_pin("Puerta Oficina L1", plaintext)
    with pytest.raises(Exception):
        decrypt_pin("Puerta Oficina L1", encrypted)


def test_pin_cipher_uses_a_separate_key_and_keeps_legacy_ciphertexts_decryptable(monkeypatch) -> None:
    jwt_secret = "legacy-jwt-secret-for-migration-tests-0123456789"
    new_pin_key = "independent-pin-encryption-key-0123456789abcdef"
    settings = Settings(environment="test", jwt_secret=jwt_secret, pin_encryption_key=new_pin_key)
    monkeypatch.setattr(pin_security, "get_settings", lambda: settings)

    encrypted_v2 = encrypt_pin("Puerta Lobby", "0042")
    assert encrypted_v2.startswith("v2:")
    assert decrypt_pin("Puerta Lobby", encrypted_v2) == "0042"

    legacy_key = hashlib.sha256(b"aegis-temporary-pins-v1\0" + jwt_secret.encode()).digest()
    nonce = b"0123456789ab"
    ciphertext = AESGCM(legacy_key).encrypt(nonce, b"0042", b"puerta lobby")
    encrypted_v1 = "v1:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    assert decrypt_pin("Puerta Lobby", encrypted_v1) == "0042"
