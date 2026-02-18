from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiSigner:
    def __init__(self, private_key_path: str) -> None:
        key_bytes = Path(private_key_path).read_bytes()
        self._key = serialization.load_pem_private_key(key_bytes, password=None)

    @staticmethod
    def path_without_query(path_or_url: str) -> str:
        parsed = urlsplit(path_or_url)
        return parsed.path if parsed.scheme else path_or_url.split("?", 1)[0]

    def sign(self, timestamp_ms: str, method: str, path_or_url: str) -> str:
        method_upper = method.upper()
        path = self.path_without_query(path_or_url)
        message = f"{timestamp_ms}{method_upper}{path}".encode("utf-8")
        signature = self._key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")
