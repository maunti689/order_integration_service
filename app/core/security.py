import hashlib
import hmac


def hash_api_key(api_key: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{api_key}".encode()).hexdigest()


def sign_webhook(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = sign_webhook(payload, secret)
    return hmac.compare_digest(expected, signature)
