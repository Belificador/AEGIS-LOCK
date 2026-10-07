"""Versioned PIN hashing and authenticated encryption with legacy-key migration."""

import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import get_settings


def _legacy_key() -> bytes:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET is required for temporary PIN protection")
    return hashlib.sha256(b"aegis-temporary-pins-v1\0" + secret.encode("utf-8")).digest()


def _encryption_key() -> bytes:
    return hashlib.sha256(b"aegis-temporary-pins-encryption-v2\0" + _pin_master_key()).digest()


def _hash_key() -> bytes:
    return hashlib.sha256(b"aegis-temporary-pins-hash-v2\0" + _pin_master_key()).digest()


def _pin_master_key() -> bytes:
    secret = get_settings().pin_encryption_key
    if not secret:
        # Local development retains compatibility with v1 PINs without requiring a secret file.
        secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("PIN_ENCRYPTION_KEY is required for temporary PIN protection")
    return hashlib.sha256(b"aegis-temporary-pins-master-v2\0" + secret.encode("utf-8")).digest()


def hash_pin(door_name: str, pin_code: str) -> str:
    message = f"{door_name.casefold()}\0{pin_code}".encode("utf-8")
    return f"v2:{hmac.new(_hash_key(), message, hashlib.sha256).hexdigest()}"


def legacy_hash_pin(door_name: str, pin_code: str) -> str:
    """Hash format used before PIN_ENCRYPTION_KEY was introduced."""
    message = f"{door_name.casefold()}\0{pin_code}".encode("utf-8")
    return hmac.new(_legacy_key(), message, hashlib.sha256).hexdigest()


def hash_pin_candidates(door_name: str, pin_code: str) -> tuple[str, str]:
    return hash_pin(door_name, pin_code), legacy_hash_pin(door_name, pin_code)


def encrypt_pin(door_name: str, pin_code: str) -> str:
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(_encryption_key()).encrypt(nonce, pin_code.encode("ascii"), door_name.casefold().encode("utf-8"))
    value = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
    return f"v2:{value}"


def decrypt_pin(door_name: str, stored_value: str) -> str:
    version, encoded = stored_value.split(":", 1)
    if version == "v1":
        key = _legacy_key()
    elif version == "v2":
        key = _encryption_key()
    else:
        raise ValueError("Unsupported encrypted PIN format")
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, door_name.casefold().encode("utf-8")).decode("ascii")
