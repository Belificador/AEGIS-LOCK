"""PIN hashing and authenticated encryption, derived from the server secret."""

import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import get_settings


def _key() -> bytes:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET is required for temporary PIN protection")
    return hashlib.sha256(b"aegis-temporary-pins-v1\0" + secret.encode("utf-8")).digest()


def hash_pin(door_name: str, pin_code: str) -> str:
    message = f"{door_name.casefold()}\0{pin_code}".encode("utf-8")
    return hmac.new(_key(), message, hashlib.sha256).hexdigest()


def encrypt_pin(door_name: str, pin_code: str) -> str:
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(_key()).encrypt(nonce, pin_code.encode("ascii"), door_name.casefold().encode("utf-8"))
    value = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
    return f"v1:{value}"


def decrypt_pin(door_name: str, stored_value: str) -> str:
    version, encoded = stored_value.split(":", 1)
    if version != "v1":
        raise ValueError("Unsupported encrypted PIN format")
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(_key()).decrypt(nonce, ciphertext, door_name.casefold().encode("utf-8")).decode("ascii")
