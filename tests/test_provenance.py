import io
import json

import numpy as np
import pytest
from PIL import Image

from nps.cli import main
from nps.core.hashing import sha256_image
from nps.core.models import AssetState, Placement
from nps.engine.base import GenerationRequest
from nps.engine.mock import MockEngine
from nps.pipeline import AssetRecord, Pipeline
from nps.product.composite import composite_product, verify_product_pixels
from nps.provenance.c2pa_sign import (
    DIGITAL_SOURCE_TYPE,
    C2paConfig,
    C2paSigner,
    ProvenanceError,
    read_credentials,
)
from nps.provenance.devcert import generate_dev_chain
from nps.provenance.seal import Sealer
from nps.provenance.watermark import (
    TrustMarkWatermarker,
    payload_for,
    watermark_around_product,
    watermarker_by_name,
)
from nps.safety.gate import MockOnlyGate
from nps.state import NOTICE_NO_C2PA, NOTICE_NO_WATERMARK, NOTICE_UNTRUSTED_C2PA

C, S = "test-campaign", "shooting-a"
AT = Placement(x=20, y=30)
ASSET = "0123456789abcdef"


class FakeWatermarker:
    """Writes the payload into the lowest blue bit, repeated; read by majority vote."""

    name = "fake"

    def __init__(self, broken=False):
        self._broken = broken

    def embed(self, image, payload_hex):
        pixels = np.array(image.convert("RGB"))
        bits = np.array([int(b) for b in format(int(payload_hex, 16), "060b")], dtype=np.uint8)
        flat = pixels[..., 2].reshape(-1)
        flat[:] = (flat & 0xFE) | np.resize(bits, flat.size)
        return Image.fromarray(pixels, mode="RGB")

    def extract(self, image):
        if self._broken:
            return None
        flat = np.asarray(image.convert("RGB"))[..., 2].reshape(-1) & 1
        usable = flat[: flat.size // 60 * 60].reshape(-1, 60)
        bits = (usable.mean(axis=0) > 0.5).astype(int)
        return format(int("".join(map(str, bits)), 2), "015x")


@pytest.fixture(scope="module")
def signer():
    chain, key = generate_dev_chain()
    return C2paSigner(C2paConfig(cert_chain_pem=chain, private_key_pem=key))


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def scene(size=(128, 128)):
    request = GenerationRequest(prompt="p", seed=1, width=size[0], height=size[1])
    return MockEngine().generate(request).image


# -- C2PA --------------------------------------------------------------------


def test_signed_file_carries_readable_credentials(signer):
    image = scene()
    signed = signer.sign_png(png_bytes(image), title="t.png", asset={"asset_id": ASSET})
    report = read_credentials(signed)
    assert report.state == "Valid" and report.intact
    assert report.digital_source_type == DIGITAL_SOURCE_TYPE
    assert report.asset == {"asset_id": ASSET}
    assert report.common_name == "DEV Signer"
    assert "not for delivery" in report.issuer
    assert "signingCredential.untrusted" in report.status_codes
    assert sha256_image(Image.open(io.BytesIO(signed)).convert("RGB")) == sha256_image(image)


def test_changed_pixels_invalidate_the_signature(signer):
    signed = signer.sign_png(png_bytes(scene()), title="t.png", asset={"asset_id": ASSET})
    tampered = bytearray(signed)
    tampered[signed.rfind(b"IDAT") + 10] ^= 0xFF
    report = read_credentials(bytes(tampered))
    assert report.state == "Invalid" and not report.intact


def test_unsigned_file_has_no_credentials():
    assert read_credentials(png_bytes(scene())) is None


def test_broken_key_is_reported_not_swallowed():
    chain, _ = generate_dev_chain()
    bad = C2paSigner(C2paConfig(cert_chain_pem=chain, private_key_pem=b"not a key"))
    with pytest.raises(ProvenanceError):
        bad.sign_png(png_bytes(scene()), title="t.png", asset={})


def test_config_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("NPS_C2PA_CERT", raising=False)
    monkeypatch.delenv("NPS_C2PA_KEY", raising=False)
    assert C2paConfig.from_env() is None
    (tmp_path / "c.pem").write_bytes(b"cert")
    monkeypatch.setenv("NPS_C2PA_CERT", str(tmp_path / "c.pem"))
    with pytest.raises(ProvenanceError, match="together"):
        C2paConfig.from_env()
    (tmp_path / "k.pem").write_bytes(b"key")
    monkeypatch.setenv("NPS_C2PA_KEY", str(tmp_path / "k.pem"))
    config = C2paConfig.from_env()
    assert (config.cert_chain_pem, config.private_key_pem, config.tsa_url) == (b"cert", b"key", None)


# -- watermark ---------------------------------------------------------------


def test_watermark_survives_and_product_stays_exact(product):
    composed = composite_product(scene(), product, AT)
    marked, check = watermark_around_product(composed, FakeWatermarker(), payload_for(ASSET), product, AT)
    assert check.passed and check.details["found"] == ASSET[:15]
    assert verify_product_pixels(marked, product, AT).passed
    assert marked.tobytes() != composed.tobytes()


def test_without_restoring_the_product_the_pixel_check_would_fail(product):
    composed = composite_product(scene(), product, AT)
    raw = FakeWatermarker().embed(composed, payload_for(ASSET))
    assert not verify_product_pixels(raw, product, AT).passed


def test_unreadable_watermark_fails_the_check(product):
    composed = composite_product(scene(), product, AT)
    _, check = watermark_around_product(composed, FakeWatermarker(broken=True), payload_for(ASSET), product, AT)
    assert not check.passed


def test_payload_rules():
    assert payload_for("ABCDEF0123456789") == "abcdef012345678"
    with pytest.raises(ValueError):
        payload_for("short")
    with pytest.raises(ValueError):
        payload_for("z" * 16)


def test_watermarker_selection():
    assert watermarker_by_name(None) is None
    assert watermarker_by_name("none") is None
    assert isinstance(watermarker_by_name("trustmark"), TrustMarkWatermarker)
    with pytest.raises(ValueError):
        watermarker_by_name("other")


# -- sealing -----------------------------------------------------------------


def seal(product, signer=None, watermarker=None):
    composed = composite_product(scene(), product, AT)
    return Sealer(signer, watermarker).seal(
        composed, product, AT, asset_id=ASSET, title="t.png", asset_info={"campaign_id": C}
    )


def test_full_seal_has_label_watermark_and_signature(product, signer):
    result = seal(product, signer, FakeWatermarker())
    assert result.passed
    assert [c.check for c in result.checks] == [
        "watermark_readback",
        "product_pixel_fidelity",
        "c2pa_readback",
    ]
    assert all(c.passed for c in result.checks)
    assert result.provenance["watermark"] == {"name": "fake", "payload": ASSET[:15]}
    assert result.provenance["c2pa"]["state"] == "Valid"

    final = Image.open(io.BytesIO(result.png)).convert("RGB")
    assert sha256_image(final) == result.pixels_sha256
    assert verify_product_pixels(final, product, AT).passed
    assert FakeWatermarker().extract(final) == ASSET[:15]
    box = result.label["box"]
    assert final.getpixel((box[0] + 1, box[1] + 1))[:2] == (0, 0)
    report = read_credentials(result.png)
    assert report.asset == {"asset_id": ASSET, "campaign_id": C}


def test_seal_without_signer_or_watermark_says_so(product):
    result = seal(product)
    assert result.passed
    assert result.provenance == {"visible_label": True, "watermark": False, "c2pa": False}
    assert read_credentials(result.png) is None


def test_failed_watermark_stops_sealing(product, signer):
    result = seal(product, signer, FakeWatermarker(broken=True))
    assert not result.passed and result.png is None
    assert result.checks[-1].check == "watermark_readback"


# -- pipeline and command line -----------------------------------------------


def run_pipeline(tmp_path, brief, product, sealer):
    pipe = Pipeline(tmp_path, MockEngine(), MockOnlyGate(), sealer=sealer)
    records = pipe.generate_variants(brief, product, "m1")
    return pipe, records


def test_pipeline_records_provenance_per_version(tmp_path, brief, product, signer):
    pipe, records = run_pipeline(tmp_path, brief, product, Sealer(signer, FakeWatermarker()))
    version = pipe.approve_variant(C, records[0].asset_id, "R")
    data = version.path.read_bytes()
    report = read_credentials(data)
    assert report.intact
    assert report.asset["asset_id"] == records[0].asset_id
    assert report.asset["engine"] == "mock" and report.asset["ai_generated"] is True
    assert "prompt" not in report.asset

    state = pipe.state(C)
    recorded = state.shootings[S].motifs["m1"].versions[0]
    assert recorded.provenance["c2pa"]["state"] == "Valid"
    assert recorded.provenance["watermark"]["payload"] == records[0].asset_id[:15]
    assert recorded.final_pixels_sha256 == sha256_image(Image.open(io.BytesIO(data)).convert("RGB"))
    assert NOTICE_UNTRUSTED_C2PA in state.notices
    assert NOTICE_NO_C2PA not in state.notices and NOTICE_NO_WATERMARK not in state.notices
    checks = [c["check"] for c in state.assets[records[0].asset_id].checks]
    assert checks[-3:] == ["watermark_readback", "product_pixel_fidelity", "c2pa_readback"]


def test_pipeline_blocks_when_sealing_fails(tmp_path, brief, product, signer):
    pipe, records = run_pipeline(tmp_path, brief, product, Sealer(signer, FakeWatermarker(broken=True)))
    result = pipe.approve_variant(C, records[0].asset_id, "R")
    assert isinstance(result, AssetRecord) and result.state is AssetState.BLOCKED
    assert not (tmp_path / "assets" / records[0].asset_id / "final.png").exists()
    assert pipe.state(C).shootings[S].motifs["m1"].versions == []


def test_cli_signs_and_inspects(tmp_path, monkeypatch, capsys):
    out = str(tmp_path / "work")
    assert main(["dev-cert", "--out", str(tmp_path / "certs")]) == 0
    monkeypatch.setenv("NPS_C2PA_CERT", str(tmp_path / "certs" / "dev-chain.pem"))
    monkeypatch.setenv("NPS_C2PA_KEY", str(tmp_path / "certs" / "dev-key.pem"))
    monkeypatch.delenv("NPS_WATERMARK", raising=False)
    assert (tmp_path / "certs" / "dev-key.pem").stat().st_mode & 0o077 == 0

    base = ["--out", out, "--campaign", "demo-herbst"]
    assert main(["run", "--demo", "--out", out, "--safety-gate", "mock_only"]) == 0
    dossier = tmp_path / "work" / "dossier-demo-herbst.json"
    asset = json.loads(dossier.read_text())["shootings"][0]["motifs"][0]["variants"][0]["asset_id"]
    assert main(["approve", *base, "--asset", asset, "--by", "R"]) == 0
    final = tmp_path / "work" / "assets" / asset / "final.png"

    capsys.readouterr()
    assert main(["inspect", *base, str(final)]) == 0
    shown = capsys.readouterr().out
    assert "C2PA: Valid" in shown and "Fassung V1" in shown and "Testzertifikat" in shown

    copy = tmp_path / "copy.png"
    Image.open(final).save(copy)  # re-encoding drops the credentials
    assert main(["inspect", *base, str(copy)]) == 2
    assert "keine Signatur" in capsys.readouterr().out

    notices = json.loads(dossier.read_text())["notices"]
    assert NOTICE_UNTRUSTED_C2PA in notices and NOTICE_NO_WATERMARK in notices
