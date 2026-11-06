from app.utils.security import hash_user_id, mask_secrets


def test_hash_stable_and_salted() -> None:
    a = hash_user_id(123456, "salt-a")
    assert a == hash_user_id(123456, "salt-a")
    assert a != hash_user_id(123456, "salt-b")
    assert a != hash_user_id(123457, "salt-a")
    assert "123456" not in a
    assert len(a) == 32


def test_mask_bot_token() -> None:
    token = "123456789:AAH4vXk3mQ9pL2sT8wZr1yBn5cD7eF0gHiJ"
    out = mask_secrets(f"request to https://api.telegram.org/bot{token}/sendMessage failed")
    assert token not in out
    assert "***" in out


def test_mask_api_keys() -> None:
    text = (
        "openai sk-proj-abcdefghijklmnopqrstuvwxyz0123 "
        "anthropic sk-ant-api03-abcdefghijklmnopqrstuvwxyz "
        "google AIzaSyA1234567890abcdefghijklmnopqrstu"
    )
    out = mask_secrets(text)
    assert "sk-proj-abc" not in out
    assert "sk-ant-api03" not in out
    assert "AIzaSyA123" not in out
    assert out.count("***") == 3


def test_mask_leaves_normal_text() -> None:
    assert mask_secrets("Post 42 published to -1001234567890") == "Post 42 published to -1001234567890"
