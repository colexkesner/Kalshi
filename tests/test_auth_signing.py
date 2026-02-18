from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kalshi_weather_hitbot.kalshi.auth import KalshiSigner


def _make_key(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "test.pem"
    path.write_bytes(pem)
    return key, str(path)


def test_signing_uses_path_without_query(tmp_path):
    priv, key_path = _make_key(tmp_path)
    signer = KalshiSigner(key_path)

    ts = "1703123456789"
    method = "GET"
    path = "/trade-api/v2/markets?status=open"

    sig_b64 = signer.sign(ts, method, path)
    assert isinstance(sig_b64, str)
    raw_sig = base64.b64decode(sig_b64)

    message = f"{ts}{method}/trade-api/v2/markets".encode()
    priv.public_key().verify(
        raw_sig,
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )


def test_path_strip_query():
    assert KalshiSigner.path_without_query("https://demo-api.kalshi.co/trade-api/v2/markets?status=open") == "/trade-api/v2/markets"
    assert KalshiSigner.path_without_query("/trade-api/v2/portfolio/balance?x=1") == "/trade-api/v2/portfolio/balance"
