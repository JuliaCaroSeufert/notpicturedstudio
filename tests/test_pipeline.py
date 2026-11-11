import json

import pytest
from PIL import Image

from nps.cli import main
from nps.core.hashing import sha256_bytes
from nps.core.models import AssetState, VersionStatus
from nps.dossier.build import build_dossier
from nps.engine.mock import MockEngine
from nps.pipeline import AssetRecord, Pipeline, PipelineError, variant_seed
from nps.product.composite import verify_product_pixels
from nps.safety.gate import BlockAllGate, MockOnlyGate
from tests.conftest import make_brief
from tests.fakes import open_upload_gate

C, S = "test-campaign", "shooting-a"


def pipeline(tmp_path, gate=None):
    return Pipeline(tmp_path, MockEngine(), gate or MockOnlyGate(), upload_gate=open_upload_gate())


def events(pipe, asset_id=None):
    return [e.event for e in pipe.log.verify() if asset_id is None or e.asset_id == asset_id]


def generated(tmp_path, brief, product):
    pipe = pipeline(tmp_path)
    records = pipe.generate_shooting(brief, product)
    return pipe, [r for r in records if r.motif_id == "m1"], [r for r in records if r.motif_id == "m2"]


# -- variants ----------------------------------------------------------------


def test_every_motif_gets_six_distinct_variants(tmp_path, brief, product):
    pipe, m1, m2 = generated(tmp_path, brief, product)
    for records in (m1, m2):
        assert len(records) == 6
        assert all(r.state is AssetState.IN_REVIEW for r in records)
        assert [r.variant for r in records] == list(range(6))
    state = pipe.state(C)
    hashes = {v.manifest["output_sha256"] for v in state.assets.values()}
    assert len(hashes) == 12
    assert len({r.asset_id for r in m1 + m2}) == 12


def test_variant_seeds_are_derived_and_recorded(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    state = pipe.state(C)
    for record in m1:
        expected = variant_seed(brief.base_seed, "m1", record.variant)
        assert state.assets[record.asset_id].seed == expected
        assert state.assets[record.asset_id].manifest["seed"] == expected


def test_motif_description_reaches_the_prompt(tmp_path, brief, product):
    pipe, m1, m2 = generated(tmp_path, brief, product)
    state = pipe.state(C)
    assert "Kind stapelt" in state.assets[m1[0].asset_id].manifest["prompt"]
    assert "Kind stapelt" not in state.assets[m2[0].asset_id].manifest["prompt"]
    assert brief.scene in state.assets[m2[0].asset_id].manifest["prompt"]


def test_more_variants_continue_the_numbering(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    extra = pipe.generate_variants(brief, product, "m1", count=2)
    assert [r.variant for r in extra] == [6, 7]
    assert not {r.asset_id for r in extra} & {r.asset_id for r in m1}


def test_runs_are_reproducible(tmp_path, brief, product):
    finals = []
    for name in ("one", "two"):
        pipe, m1, _ = generated(tmp_path / name, brief, product)
        finals.append(pipe.approve_variant(C, m1[2].asset_id, "R").path.read_bytes())
    assert finals[0] == finals[1]


def test_registered_shooting_is_frozen(tmp_path, brief, product):
    pipe, _, _ = generated(tmp_path, brief, product)
    with pytest.raises(PipelineError, match="new shooting id"):
        pipe.generate_variants(make_brief(scene="Garten im Sommer"), product, "m1")
    other = product.copy()
    other.putpixel((10, 10), (1, 2, 3, 255))
    with pytest.raises(PipelineError):
        pipe.generate_variants(brief, other, "m1")


def test_default_gate_blocks_and_stores_no_scene(tmp_path, brief, product):
    pipe = pipeline(tmp_path, BlockAllGate())
    records = pipe.generate_shooting(brief, product)
    assert len(records) == 12
    assert all(r.state is AssetState.BLOCKED for r in records)
    assert not list((tmp_path / "assets").rglob("*.png")) if (tmp_path / "assets").exists() else True
    with pytest.raises(PipelineError):
        pipe.approve_variant(C, records[0].asset_id, "R")


def test_excluded_brief_generates_nothing(tmp_path, product):
    pipe = pipeline(tmp_path)
    records = pipe.generate_shooting(make_brief(product_category="diapers"), product)
    assert [r.state for r in records] == [AssetState.REJECTED]
    assert events(pipe) == ["brief_rejected"]  # rejected before the product is even looked at
    assert not list(tmp_path.rglob("*.png"))


# -- internal review and versions --------------------------------------------


def test_approval_seals_the_variant_as_v1(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    asset = m1[3].asset_id
    assert not (tmp_path / "assets" / asset / "final.png").exists()

    version = pipe.approve_variant(C, asset, "Erika Beispiel")
    assert (version.number, version.status) == (1, VersionStatus.SEALED)
    assert events(pipe, asset) == [
        "asset_planned",
        "asset_generated",
        "safety_passed",
        "asset_in_review",
        "asset_approved",
        "asset_sealed",
    ]
    final = Image.open(version.path)
    assert verify_product_pixels(final, product, brief.motif("m1").placement).passed
    recorded = pipe.state(C).shootings[S].motifs["m1"].versions[0]
    assert recorded.final_sha256 == sha256_bytes(version.path.read_bytes())
    assert recorded.approved_by == "Erika Beispiel"
    assert recorded.parent is None
    assert recorded.provenance == {"visible_label": True, "c2pa": False, "watermark": False}


def test_review_needs_a_name(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    with pytest.raises(PipelineError):
        pipe.approve_variant(C, m1[0].asset_id, "  ")
    assert "asset_sealed" not in events(pipe)


def test_rejected_variant_cannot_be_approved(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    assert pipe.reject_variant(C, m1[0].asset_id, "R", "Licht passt nicht").state is AssetState.REJECTED
    with pytest.raises(PipelineError):
        pipe.approve_variant(C, m1[0].asset_id, "R")


def test_only_one_open_version_per_motif(tmp_path, brief, product):
    pipe, m1, m2 = generated(tmp_path, brief, product)
    pipe.approve_variant(C, m1[0].asset_id, "R")
    with pytest.raises(PipelineError, match="change request"):
        pipe.approve_variant(C, m1[1].asset_id, "R")
    # Another motif is independent.
    assert pipe.approve_variant(C, m2[0].asset_id, "R").number == 1


def test_image_changed_after_checks_is_blocked(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    tampered = Image.open(m1[0].path).convert("RGB")
    tampered.putpixel((0, 0), (1, 2, 3))
    tampered.save(m1[0].path)
    result = pipe.approve_variant(C, m1[0].asset_id, "R")
    assert isinstance(result, AssetRecord) and result.state is AssetState.BLOCKED
    assert "asset_sealed" not in events(pipe)
    assert pipe.state(C).shootings[S].motifs["m1"].versions == []


def test_swapped_product_file_is_detected(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    stored = next((tmp_path / "products").glob("*.png"))
    Image.new("RGBA", product.size, (0, 255, 0, 255)).save(stored)
    with pytest.raises(PipelineError, match="product"):
        pipe.approve_variant(C, m1[0].asset_id, "R")


# -- client ------------------------------------------------------------------


def test_change_request_leads_to_v2_with_parent(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    pipe.approve_variant(C, m1[0].asset_id, "R")
    pipe.release_version(C, S, "m1", 1, "R")
    changed = pipe.customer_decision(C, S, "m1", 1, approved=False, recorded_by="R", comment="wärmer")
    assert changed.status is VersionStatus.CHANGES_REQUESTED

    v2 = pipe.approve_variant(C, m1[1].asset_id, "R", note="nach Kundenwunsch")
    assert v2.number == 2
    pipe.release_version(C, S, "m1", 2, "R")
    pipe.customer_decision(C, S, "m1", 2, approved=True, recorded_by="R")

    versions = pipe.state(C).shootings[S].motifs["m1"].versions
    assert [(v.number, v.parent, v.status) for v in versions] == [
        (1, None, VersionStatus.CHANGES_REQUESTED),
        (2, 1, VersionStatus.CUSTOMER_APPROVED),
    ]
    assert versions[0].customer["comment"] == "wärmer"
    assert versions[1].asset_id == m1[1].asset_id


def test_client_steps_follow_a_fixed_order(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    with pytest.raises(PipelineError, match="unknown version"):
        pipe.release_version(C, S, "m1", 1, "R")
    pipe.approve_variant(C, m1[0].asset_id, "R")
    with pytest.raises(PipelineError, match="expected 'released'"):
        pipe.customer_decision(C, S, "m1", 1, approved=True, recorded_by="R")
    pipe.release_version(C, S, "m1", 1, "R")
    with pytest.raises(PipelineError):
        pipe.release_version(C, S, "m1", 1, "R")
    with pytest.raises(PipelineError, match="comment"):
        pipe.customer_decision(C, S, "m1", 1, approved=False, recorded_by="R")
    pipe.customer_decision(C, S, "m1", 1, approved=True, recorded_by="R")
    with pytest.raises(PipelineError):
        pipe.customer_decision(C, S, "m1", 1, approved=False, recorded_by="R", comment="doch nicht")
    with pytest.raises(PipelineError, match="change request"):
        pipe.approve_variant(C, m1[1].asset_id, "R")


@pytest.mark.parametrize("number", [0, -1, 2])
def test_unknown_version_numbers_are_errors(tmp_path, brief, product, number):
    pipe, m1, _ = generated(tmp_path, brief, product)
    pipe.approve_variant(C, m1[0].asset_id, "R")
    with pytest.raises(PipelineError, match="unknown version"):
        pipe.release_version(C, S, "m1", number, "R")


# -- dossier and command line ------------------------------------------------


def test_dossier_reflects_the_chain(tmp_path, brief, product):
    pipe, m1, _ = generated(tmp_path, brief, product)
    pipe.approve_variant(C, m1[0].asset_id, "Erika Beispiel")
    pipe.release_version(C, S, "m1", 1, "Erika Beispiel")
    pipe.generate_shooting(make_brief(shooting_id="shooting-b", product_category="bath"), product)
    pipe.generate_shooting(make_brief(campaign_id="other-campaign"), product)

    dossier = build_dossier(pipe.log, C)
    json.dumps(dossier)
    assert dossier["chain"]["verified"] is True
    assert dossier["chain"]["entries_campaign"] < dossier["chain"]["entries_total"]
    assert [r["shooting_id"] for r in dossier["rejected_briefs"]] == ["shooting-b"]
    (shooting,) = dossier["shootings"]
    motif = shooting["motifs"][0]
    assert len(motif["variants"]) == 6
    assert motif["versions"][0]["status"] == "released"
    assert motif["versions"][0]["approved_by"] == "Erika Beispiel"
    assert motif["variants"][0]["state"] == "sealed"
    assert all(check["passed"] for check in motif["variants"][0]["checks"])
    assert len(dossier["notices"]) == 4


def test_cli_flow(tmp_path, capsys):
    assert main(["run", "--demo", "--out", str(tmp_path / "blocked"), "--upload-gate", "demo_only"]) == 2
    out = str(tmp_path / "ok")
    base = ["--out", out, "--campaign", "demo-herbst"]
    version = base + ["--shooting", "kinderzimmer", "--motif", "stapeln", "--version", "1", "--by", "R"]

    assert main(["run", "--demo", "--out", out, "--safety-gate", "mock_only", "--upload-gate", "demo_only"]) == 0
    dossier_path = tmp_path / "ok" / "dossier-demo-herbst.json"
    asset = json.loads(dossier_path.read_text())["shootings"][0]["motifs"][0]["variants"][1]["asset_id"]

    assert main(["approve", *base, "--asset", asset, "--by", "R"]) == 0
    assert main(["approve", *base, "--asset", asset, "--by", "R"]) == 1
    assert main(["release", *version]) == 0
    assert main(["customer", *version]) == 0
    assert main(["status", *base]) == 0
    assert "Fassung V1" in capsys.readouterr().out
    assert main(["verify", "--out", out]) == 0
    motif = json.loads(dossier_path.read_text())["shootings"][0]["motifs"][0]
    assert motif["versions"][0]["status"] == "customer_approved"

    log = tmp_path / "ok" / "audit.jsonl"
    log.write_text(log.read_text().replace('"approved_by":"R"', '"approved_by":"X"'))
    assert main(["verify", "--out", out]) == 1
    assert main(["status", *base]) == 1
