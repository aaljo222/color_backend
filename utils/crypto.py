"""utils/crypto.py — 필드 레벨 암호화 (AES-256-GCM). 키: MEMORY_ENC_KEY (base64, 32바이트).
키 생성:  python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
"""
import base64, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key() -> bytes:
    k = os.getenv("MEMORY_ENC_KEY")
    if not k:
        raise RuntimeError("MEMORY_ENC_KEY 미설정 — 원문 보관 기능을 쓸 수 없습니다.")
    raw = base64.b64decode(k)
    if len(raw) != 32:
        raise RuntimeError("MEMORY_ENC_KEY 는 32바이트(base64)여야 합니다.")
    return raw


def encrypt(text: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, text.encode("utf-8"), b"mac-memory-v1")
    return base64.b64encode(nonce + ct).decode()


def decrypt(token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], b"mac-memory-v1").decode("utf-8")


def enabled() -> bool:
    return bool(os.getenv("MEMORY_ENC_KEY"))
