"""Invisible watermark behind an interface, plus the TrustMark adapter.

A watermark changes pixels slightly across the whole image. Product pixels must
stay exactly as photographed, so they are restored after embedding and the
watermark is then read back; if it no longer decodes, sealing fails.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from PIL import Image

from nps.core.models import CheckResult, Placement

# 15 hex characters = 60 bits, which fits TrustMark's 61-bit payload.
PAYLOAD_HEX_CHARS = 15


class Watermarker(Protocol):
    name: str

    def embed(self, image: Image.Image, payload_hex: str) -> Image.Image: ...

    def extract(self, image: Image.Image) -> str | None: ...


def payload_for(asset_id: str) -> str:
    payload = asset_id[:PAYLOAD_HEX_CHARS].lower()
    if len(payload) != PAYLOAD_HEX_CHARS or any(c not in "0123456789abcdef" for c in payload):
        raise ValueError("watermark payload needs an asset id of at least 15 hex characters")
    return payload


def restore_product_core(
    image: Image.Image, product: Image.Image, placement: Placement
) -> Image.Image:
    """Copy the fully opaque product pixels back, exactly."""
    pixels = np.array(image.convert("RGB"))
    source = np.asarray(product)
    core = source[..., 3] == 255
    region = pixels[
        placement.y : placement.y + product.height, placement.x : placement.x + product.width
    ]
    region[core] = source[..., :3][core]
    return Image.fromarray(pixels, mode="RGB")


def watermark_around_product(
    image: Image.Image,
    watermarker: Watermarker,
    payload_hex: str,
    product: Image.Image,
    placement: Placement,
) -> tuple[Image.Image, CheckResult]:
    marked = watermarker.embed(image, payload_hex).convert("RGB")
    if marked.size != image.size:
        raise ValueError("watermarker changed the image size")
    marked = restore_product_core(marked, product, placement)
    found = watermarker.extract(marked)
    return marked, CheckResult(
        check="watermark_readback",
        passed=found == payload_hex,
        details={"watermarker": watermarker.name, "expected": payload_hex, "found": found},
    )


class TrustMarkWatermarker:
    """Adobe/CAI TrustMark (MIT). Needs the `watermark` extra and its model files.

    The model files are downloaded on first use from cai-watermark.adobe.net.
    """

    name = "trustmark"

    def __init__(self, model_type: str = "Q", device: str = "") -> None:
        self._model_type = model_type
        self._device = device
        self._tm: Any = None

    def _model(self) -> Any:
        if self._tm is None:
            from trustmark import TrustMark

            self._tm = TrustMark(verbose=False, model_type=self._model_type, device=self._device)
        return self._tm

    def embed(self, image: Image.Image, payload_hex: str) -> Image.Image:
        model = self._model()
        capacity = model.schemaCapacity()
        bits = format(int(payload_hex, 16), f"0{len(payload_hex) * 4}b")
        if len(bits) > capacity:
            raise ValueError(f"payload of {len(bits)} bits exceeds capacity of {capacity} bits")
        return model.encode(image.convert("RGB"), bits.ljust(capacity, "0"), MODE="binary")

    def extract(self, image: Image.Image) -> str | None:
        bits, detected, _version = self._model().decode(image.convert("RGB"), MODE="binary")
        if not detected:
            return None
        used = PAYLOAD_HEX_CHARS * 4
        return format(int(bits[:used], 2), f"0{PAYLOAD_HEX_CHARS}x")


def watermarker_by_name(name: str | None) -> Watermarker | None:
    if not name or name == "none":
        return None
    if name == TrustMarkWatermarker.name:
        return TrustMarkWatermarker()
    raise ValueError(f"unknown watermarker '{name}', expected 'trustmark' or 'none'")
