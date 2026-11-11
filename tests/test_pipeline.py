import json

import pytest
from PIL import Image

from nps.cli import main
from nps.core.hashing import sha256_bytes
from nps.core.models import AssetState
from nps.dossier.build import build_dossier
from nps.engine.mock import MockEngine
from nps.pipeline import Pipeline, PipelineError
from nps.product.composite import verify_product_pixels
from nps.safety.gate import BlockAllGate, MockOnlyGate
from tests.conftest import make_brief


def pipeline(tmp_path, gate=None):
    return Pipeline(tmp_path, MockEngine(), gate or MockOnlyGate())


def events(pipe, asset_id=None):
    return [entry.event for entry in pipe.log.verify() if asset_id is None or entry.asset_id == asset_id]


def test_end_to_end_to_sealed_file(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    in_review = pipe.generate(brief, product)
    assert in_review.state is AssetState.IN_REVIEW
    assert not (tmp_path / "assets" / in_review.asset_id / "final.png").exists()

    sealed = pipe.review(brief, in_review.asset_id, "Erika Beispiel", approve=True)
    assert sealed.state is AssetState.SEALED
    assert events(pipe, sealed.asset_id) == [
        "asset_planned",
        "asset_generated",
        "safety_passed",
        "asset_in_review",
        "asset_approved",
        "asset_sealed",
    ]

    final = Image.open(sealed.path)
    assert final.size == (brief.width, brief.height)
    assert verify_product_pixels(final, product, brief.placement).passed
    seal = pipe.log.verify()[-1].payload
    assert seal["final_sha256"] == sha256_bytes(sealed.path.read_bytes())
    assert seal["provenance"] == {"visible_label": True, "c2pa": False, "watermark": False}


def test_run_is_reproducible(tmp_path, brief, product):
    finals = []
    for name in ("one", "two"):
        pipe = pipeline(tmp_path / name)
        record = pipe.generate(brief, product)
        finals.append(pipe.review(brief, record.asset_id, "R", approve=True).path.read_bytes())
    assert finals[0] == finals[1]


def test_default_gate_blocks_and_stores_no_image(tmp_path, brief, product):
    pipe = pipeline(tmp_path, BlockAllGate())
    record = pipe.generate(brief, product)
    assert record.state is AssetState.BLOCKED
    assert events(pipe)[-1] == "asset_blocked"
    assert not list(tmp_path.rglob("*.png"))
    with pytest.raises(PipelineError):
        pipe.review(brief, record.asset_id, "R", approve=True)


def test_excluded_brief_generates_nothing(tmp_path, product):
    pipe = pipeline(tmp_path)
    record = pipe.generate(make_brief(product_category="diapers"), product)
    assert record.state is AssetState.REJECTED
    assert events(pipe) == ["brief_rejected"]
    assert not list(tmp_path.rglob("*.png"))


def test_nothing_is_sealed_without_review(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    record = pipe.generate(brief, product)
    with pytest.raises(PipelineError):
        pipe.review(brief, record.asset_id, "  ", approve=True)
    assert "asset_sealed" not in events(pipe)


def test_rejection_is_final(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    record = pipe.generate(brief, product)
    rejected = pipe.review(brief, record.asset_id, "R", approve=False, note="Licht passt nicht")
    assert rejected.state is AssetState.REJECTED
    with pytest.raises(PipelineError):
        pipe.review(brief, record.asset_id, "R", approve=True)
    assert not (tmp_path / "assets" / record.asset_id / "final.png").exists()


def test_asset_cannot_be_reviewed_twice(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    record = pipe.generate(brief, product)
    pipe.review(brief, record.asset_id, "R", approve=True)
    with pytest.raises(PipelineError):
        pipe.review(brief, record.asset_id, "R", approve=True)


def test_image_changed_after_checks_is_blocked(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    record = pipe.generate(brief, product)
    tampered = Image.open(record.path).convert("RGB")
    tampered.putpixel((0, 0), (1, 2, 3))
    tampered.save(record.path)
    result = pipe.review(brief, record.asset_id, "R", approve=True)
    assert result.state is AssetState.BLOCKED
    assert "asset_sealed" not in events(pipe)


def test_same_brief_cannot_be_generated_twice(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    pipe.generate(brief, product)
    with pytest.raises(PipelineError):
        pipe.generate(brief, product)


def test_dossier_reflects_the_chain(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    record = pipe.generate(brief, product)
    pipe.review(brief, record.asset_id, "Erika Beispiel", approve=True)
    pipe.generate(make_brief(product_category="bath"), product)

    dossier = build_dossier(pipe.log, brief.campaign_id)
    assert dossier["chain"]["verified"] is True
    assert dossier["chain"]["head_hash"] == pipe.log.verify()[-1].hash
    assert len(dossier["rejected_briefs"]) == 1
    (asset,) = dossier["assets"]
    assert asset["state"] == "sealed"
    assert asset["review"]["reviewer"] == "Erika Beispiel"
    assert asset["manifest"]["seed"] == brief.seed
    assert all(check["passed"] for check in asset["checks"])
    assert len(dossier["notices"]) == 3


def test_dossier_is_limited_to_its_campaign(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    pipe.generate(brief, product)
    pipe.generate(make_brief(campaign_id="other-campaign"), product)
    assert len(build_dossier(pipe.log, "test-campaign")["assets"]) == 1


def test_cli_demo(tmp_path, capsys):
    assert main(["run", "--demo", "--out", str(tmp_path / "blocked")]) == 2
    out = tmp_path / "ok"
    assert main(["run", "--demo", "--out", str(out), "--safety-gate", "mock_only", "--approve-as", "R"]) == 0
    assert main(["verify", "--out", str(out)]) == 0
    dossier = json.loads((out / "dossier-demo-herbst.json").read_text(encoding="utf-8"))
    assert dossier["assets"][0]["state"] == "sealed"

    log = out / "audit.jsonl"
    log.write_text(log.read_text().replace("Test-Engine", "x").replace('"seed":1234', '"seed":1235'))
    assert main(["verify", "--out", str(out)]) == 1
