from app.services.beta_auth import hash_password, hash_session_token, verify_password


def test_password_hash_verification() -> None:
    password_hash = hash_password("strong-password")

    assert password_hash != "strong-password"
    assert verify_password("strong-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_session_token_hash_is_stable_and_not_plaintext() -> None:
    token = "session-token"

    assert hash_session_token(token) == hash_session_token(token)
    assert hash_session_token(token) != token
