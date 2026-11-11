"""Sealing: visible label, invisible watermark, C2PA signature, in that order."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image

from nps.core.hashing import sha256_image
from nps.core.models import CheckResult, Placement
from nps.product.composite import product_box, verify_product_pixels
from nps.provenance.c2pa_sign import DIGITAL_SOURCE_TYPE, C2paSigner, read_credentials
from nps.provenance.label import LABEL_TEXT, apply_visible_label
from nps.provenance.watermark import Watermarker, payload_for, watermark_around_product


@dataclass(frozen=True)
class SealResult:
    checks: tuple[CheckResult, ...]
    png: bytes | None = None
    pixels_sha256: str | None = None
    label: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.png is not None


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class Sealer:
    """Without signer or watermarker the file gets only the visible label.

    That is allowed for development; the recorded provenance says what is
    missing, and the dossier repeats it.
    """

    def __init__(self, signer: C2paSigner | None = None, watermarker: Watermarker | None = None):
        self._signer = signer
        self._watermarker = watermarker

    def seal(
        self,
        composed: Image.Image,
        product: Image.Image,
        placement: Placement,
        *,
        asset_id: str,
        title: str,
        asset_info: dict[str, Any],
    ) -> SealResult:
        checks: list[CheckResult] = []
        image, label_box = apply_visible_label(composed, product_box(product, placement))
        provenance: dict[str, Any] = {"visible_label": True, "watermark": False, "c2pa": False}

        if self._watermarker is not None:
            payload = payload_for(asset_id)
            image, readback = watermark_around_product(
                image, self._watermarker, payload, product, placement
            )
            checks.append(readback)
            if not readback.passed:
                return SealResult(tuple(checks))
            provenance["watermark"] = {"name": self._watermarker.name, "payload": payload}

        fidelity = verify_product_pixels(image, product, placement)
        checks.append(fidelity)
        if not fidelity.passed:
            return SealResult(tuple(checks))

        pixels = sha256_image(image)
        png = _encode_png(image)

        if self._signer is not None:
            png = self._signer.sign_png(png, title=title, asset={"asset_id": asset_id, **asset_info})
            # Read the signed file back: the credentials must validate, name this
            # asset, and the pixels must be the ones that were checked above.
            report = read_credentials(png)
            signed = Image.open(io.BytesIO(png))
            signed.load()
            ok = (
                report is not None
                and report.intact
                and report.digital_source_type == DIGITAL_SOURCE_TYPE
                and (report.asset or {}).get("asset_id") == asset_id
                and sha256_image(signed.convert("RGB")) == pixels
            )
            checks.append(
                CheckResult(
                    check="c2pa_readback",
                    passed=ok,
                    details={
                        "state": report.state if report else None,
                        "status_codes": list(report.status_codes) if report else [],
                    },
                )
            )
            if not ok:
                return SealResult(tuple(checks))
            provenance["c2pa"] = report.as_dict()

        return SealResult(
            checks=tuple(checks),
            png=png,
            pixels_sha256=pixels,
            label={"text": LABEL_TEXT, "box": list(label_box)},
            provenance=provenance,
        )
