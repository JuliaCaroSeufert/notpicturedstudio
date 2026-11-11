"""C2PA Content Credentials: sign the finished file and read credentials back.

Signing is the last step of sealing. Nothing may change the file afterwards,
because the signature covers its bytes.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nps

# The image combines a generated scene with a photographed product.
DIGITAL_SOURCE_TYPE = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
)
ASSET_ASSERTION = "com.notpicturedstudio.asset"
_PNG = "image/png"

# "Valid": signature and content hash are intact, signer not on a trust list
# (test certificate). "Trusted": the same, signed with a recognised certificate.
ACCEPTED_STATES = ("Valid", "Trusted")


class ProvenanceError(Exception):
    """Signing or reading Content Credentials failed."""


@dataclass(frozen=True)
class CredentialReport:
    state: str
    issuer: str | None
    common_name: str | None
    digital_source_type: str | None
    asset: dict[str, Any] | None
    status_codes: tuple[str, ...]

    @property
    def intact(self) -> bool:
        return self.state in ACCEPTED_STATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "issuer": self.issuer,
            "common_name": self.common_name,
            "digital_source_type": self.digital_source_type,
        }


@dataclass(frozen=True)
class C2paConfig:
    cert_chain_pem: bytes
    private_key_pem: bytes
    alg: str = "es256"
    # RFC 3161 timestamp service. Without one the signature carries no trusted time.
    tsa_url: str | None = None

    @classmethod
    def from_env(cls) -> "C2paConfig | None":
        """Read certificate and key locations from the environment, never from the repo."""
        cert, key = os.environ.get("NPS_C2PA_CERT"), os.environ.get("NPS_C2PA_KEY")
        if not cert and not key:
            return None
        if not cert or not key:
            raise ProvenanceError("NPS_C2PA_CERT and NPS_C2PA_KEY must be set together")
        return cls(
            cert_chain_pem=Path(cert).read_bytes(),
            private_key_pem=Path(key).read_bytes(),
            alg=os.environ.get("NPS_C2PA_ALG", "es256"),
            tsa_url=os.environ.get("NPS_C2PA_TSA_URL") or None,
        )


class C2paSigner:
    def __init__(self, config: C2paConfig) -> None:
        self._config = config

    def sign_png(self, png: bytes, *, title: str, asset: dict[str, Any]) -> bytes:
        import c2pa

        generator = {"name": "notpicturedstudio", "version": nps.__version__}
        manifest = {
            "claim_generator_info": [generator],
            "title": title,
            "assertions": [
                {
                    "label": "c2pa.actions",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": DIGITAL_SOURCE_TYPE,
                                "softwareAgent": generator,
                            }
                        ]
                    },
                },
                {"label": ASSET_ASSERTION, "data": asset},
            ],
        }
        config = self._config
        try:
            info = c2pa.C2paSignerInfo(
                alg=config.alg.encode("ascii"),
                sign_cert=config.cert_chain_pem,
                private_key=config.private_key_pem,
                ta_url=config.tsa_url.encode("ascii") if config.tsa_url else None,
            )
            signer = c2pa.Signer.from_info(info)
            destination = io.BytesIO()
            c2pa.Builder(manifest).sign(signer, _PNG, io.BytesIO(png), destination)
        except c2pa.C2paError as error:
            raise ProvenanceError(f"C2PA signing failed: {error}") from error
        return destination.getvalue()


def read_credentials(png: bytes) -> CredentialReport | None:
    """Return the credentials of a PNG, or None if it carries none."""
    import c2pa

    try:
        reader = c2pa.Reader(_PNG, io.BytesIO(png))
    except c2pa.C2paError.ManifestNotFound:
        return None
    except c2pa.C2paError as error:
        raise ProvenanceError(f"C2PA data could not be read: {error}") from error

    data = json.loads(reader.json())
    manifest = data["manifests"][data["active_manifest"]]
    signature = manifest.get("signature_info") or {}
    source_type, asset = None, None
    for assertion in manifest.get("assertions", []):
        if assertion["label"].startswith("c2pa.actions"):
            for action in assertion["data"].get("actions", []):
                source_type = action.get("digitalSourceType", source_type)
        elif assertion["label"] == ASSET_ASSERTION:
            asset = assertion["data"]
    return CredentialReport(
        state=str(reader.get_validation_state()),
        issuer=signature.get("issuer"),
        common_name=signature.get("common_name"),
        digital_source_type=source_type,
        asset=asset,
        status_codes=tuple(status["code"] for status in data.get("validation_status", [])),
    )
