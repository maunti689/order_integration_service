from app.core.security import (
    hash_api_key,
    sign_webhook,
    verify_webhook_signature,
)


def test_api_key_hash_is_deterministic():
    assert hash_api_key("secret", "salt") == hash_api_key("secret", "salt")


def test_api_key_hash_changes_with_salt():
    assert hash_api_key("secret", "salt-a") != hash_api_key("secret", "salt-b")


def test_webhook_signature_verification():
    payload = b'{"event_id":"evt-1"}'
    signature = sign_webhook(payload, "secret")
    assert verify_webhook_signature(payload, signature, "secret")
    assert not verify_webhook_signature(payload + b"x", signature, "secret")
