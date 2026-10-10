from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.core.config import settings

_VERSION = b"EM1"
_NONCE_SIZE = 16
_TAG_SIZE = 32


def _derive_key(purpose: bytes) -> bytes:
    return hmac.new(settings.jwt_secret.encode(), b"runtime-secret:" + purpose, hashlib.sha256).digest()


def _key_stream(nonce: bytes, length: int) -> bytes:
    encryption_key = _derive_key(b"encryption")
    blocks: list[bytes] = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(
            hmac.new(
                encryption_key,
                _VERSION + nonce + counter.to_bytes(4, "big"),
                hashlib.sha256,
            ).digest()
        )
        counter += 1
    return b"".join(blocks)[:length]


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    plaintext = value.encode()
    nonce = secrets.token_bytes(_NONCE_SIZE)
    stream = _key_stream(nonce, len(plaintext))
    ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream, strict=True))
    payload = _VERSION + nonce + ciphertext
    tag = hmac.new(_derive_key(b"authentication"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + tag).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        payload_with_tag = base64.urlsafe_b64decode(token.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError("密钥配置无法解码") from exc
    minimum_size = len(_VERSION) + _NONCE_SIZE + _TAG_SIZE
    if len(payload_with_tag) < minimum_size:
        raise ValueError("密钥配置长度无效")
    payload, supplied_tag = payload_with_tag[:-_TAG_SIZE], payload_with_tag[-_TAG_SIZE:]
    expected_tag = hmac.new(_derive_key(b"authentication"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(supplied_tag, expected_tag):
        raise ValueError("密钥配置校验失败")
    if not payload.startswith(_VERSION):
        raise ValueError("密钥配置版本不受支持")
    nonce = payload[len(_VERSION) : len(_VERSION) + _NONCE_SIZE]
    ciphertext = payload[len(_VERSION) + _NONCE_SIZE :]
    stream = _key_stream(nonce, len(ciphertext))
    plaintext = bytes(left ^ right for left, right in zip(ciphertext, stream, strict=True))
    try:
        return plaintext.decode()
    except UnicodeDecodeError as exc:
        raise ValueError("密钥配置内容无效") from exc
