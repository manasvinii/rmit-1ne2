import logging
import time

from app.core import security
from app.core.security import (
    RedactingFilter,
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    is_encrypted,
    redact,
    sign_resource_url,
    verify_legacy_plaintext,
    verify_password,
    verify_resource_signature,
)


def test_passwords_are_bcrypt_hashed():
    h = hash_password("s3cret-pass")
    assert h.startswith("$2") and "s3cret-pass" not in h
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
    assert not verify_password("s3cret-pass", "s3cret-pass")  # plaintext is never accepted as a hash


def test_legacy_plaintext_only_matches_unhashed_rows():
    assert verify_legacy_plaintext("old", "old")
    assert not verify_legacy_plaintext("old", hash_password("old"))


def test_jwt_roundtrip_and_tamper():
    tok = create_access_token("1234567")
    assert decode_access_token(tok) == "1234567"
    assert decode_access_token(tok[:-2] + "xx") is None
    assert decode_access_token("not-a-token") is None


def test_canvas_token_encrypted_at_rest():
    raw = "7036~AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    enc = encrypt_secret(raw)
    assert is_encrypted(enc) and raw not in enc
    assert decrypt_secret(enc) == raw
    assert decrypt_secret("enc:v1:garbage") is None


def test_signed_resource_urls_bind_user_resource_and_expiry():
    exp, sig = sign_resource_url("u1", "r1")
    assert verify_resource_signature("u1", "r1", exp, sig)
    assert not verify_resource_signature("u2", "r1", exp, sig)
    assert not verify_resource_signature("u1", "r2", exp, sig)
    assert not verify_resource_signature("u1", "r1", exp + 1, sig)
    past = int(time.time()) - 10
    msg_sig = sign_resource_url("u1", "r1", ttl=1)[1]
    assert not verify_resource_signature("u1", "r1", past, msg_sig)


def test_redaction_of_tokens_in_logs():
    text = ('Authorization: Bearer abc.def.ghi canvas=7036~AbCdEfGhIjKlMnOpQrStUvWx '
            'key sk-abcdefghijklmnopqrstu {"password": "hunter22", "api_token": "zzz"}')
    out = redact(text)
    for secret in ("abc.def.ghi", "7036~AbCdEfGhIjKlMnOpQrStUvWx", "sk-abcdefghijklmnopqrstu", "hunter22", "zzz"):
        assert secret not in out


def test_logging_filter_redacts_records():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "token=%s", ("supersecretvalue",), None)
    RedactingFilter().filter(rec)
    assert "supersecretvalue" not in rec.getMessage()


def test_dev_secret_refused_in_production(monkeypatch):
    class S:
        env = "production"
        sqlite_path = "/tmp/x.db"

    monkeypatch.setattr(security, "get_settings", lambda: S())
    try:
        security._dev_secret("JWT_SECRET", lambda: "x")
    except RuntimeError:
        return
    raise AssertionError("production must require explicit secrets")
