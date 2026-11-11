"""Canonical hashing helpers used by the audit chain and manifests."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from PIL import Image


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    """Serialise to a stable JSON form: sorted keys, no extra whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_image(image: Image.Image) -> str:
    """Hash the decoded pixels, so the result does not depend on file encoding."""
    header = f"{image.mode}:{image.width}x{image.height}:".encode("ascii")
    return sha256_bytes(header + image.tobytes())
