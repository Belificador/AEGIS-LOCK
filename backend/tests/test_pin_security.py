import pytest

from backend.core.pin_security import decrypt_pin, encrypt_pin, hash_pin


def test_temporary_pin_ciphertext_and_door_binding() -> None:
    plaintext = "0042"
    encrypted = encrypt_pin("Puerta Lobby", plaintext)
    assert plaintext not in encrypted
    assert decrypt_pin("Puerta Lobby", encrypted) == plaintext
    assert hash_pin("Puerta Lobby", plaintext) == hash_pin("Puerta Lobby", plaintext)
    assert hash_pin("Puerta Lobby", plaintext) != hash_pin("Puerta Oficina L1", plaintext)
    with pytest.raises(Exception):
        decrypt_pin("Puerta Oficina L1", encrypted)
