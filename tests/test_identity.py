import io

import pytest
from PIL import Image

import nps.identity.register as reg
from nps.core.models import AssetState
from nps.dossier.build import build_dossier
from nps.engine.base import GenerationInputs, GenerationRequest, check_inputs
from nps.engine.mock import MockEngine
from nps.identity.register import (
    IdentityRegister,
    IdentityStatus,
    MockTrainer,
    RegisterError,
    VersionStage,
)
from nps.pipeline import Pipeline, PipelineError
from nps.provenance.c2pa_sign import C2paConfig, C2paSigner, read_credentials
from nps.provenance.devcert import generate_dev_chain
from nps.safety.gate import BlockAllGate, MockOnlyGate
from tests.conftest import make_brief
from tests.engine_fakes import FakeBackend
from tests.fakes import open_upload_gate

BRAND = "Testmarke"


@pytest.fixture(scope="module")
def signer():
    chain, key = generate_dev_chain()
    return C2paSigner(C2paConfig(cert_chain_pem=chain, private_key_pem=key))


@pytest.fixture(autouse=True)
def small_images(monkeypatch):
    monkeypatch.setattr(reg, "IMAGE_SIZE", 96)


def register(tmp_path, signer, gate=None, engine=None, trainer=MockTrainer()):
    return IdentityRegister(tmp_path, engine or MockEngine(), gate or MockOnlyGate(), signer, trainer=trainer)


def selected(tmp_path, signer, age=4):
    r = register(tmp_path, signer)
    (identity_id,) = r.propose("braune Locken, Sommersprossen", age, 1, "Anna")
    r.endorse(identity_id, "Anna")
    r.endorse(identity_id, "Ben")
    return r, identity_id


def frozen(tmp_path, signer, age=4):
    r, identity_id = selected(tmp_path, signer, age)
    r.extend_dataset(identity_id, 8)
    r.approve_dataset(identity_id, "Anna")
    r.train(identity_id, "Anna")
    r.freeze(identity_id, "Ben")
    return r, identity_id


# -- 1. propose --------------------------------------------------------------


def test_candidates_are_generated_signed_and_logged(tmp_path, signer):
    r = register(tmp_path, signer)
    ids = r.propose("braune Locken", 4, 3, "Anna")
    assert len(set(ids)) == 3
    for identity_id in ids:
        identity = r.get(identity_id)
        assert identity.status is IdentityStatus.CANDIDATE and identity.engine == "mock"
        (image,) = identity.versions[1].images
        data = r.image_path(identity_id, image.sha256).read_bytes()
        report = read_credentials(data)
        assert report.intact and report.asset["identity_id"] == identity_id
        assert report.asset["role"] == "candidate"
    assert len({r.get(i).versions[1].images[0].pixels_sha256 for i in ids}) == 3
    assert len({r.get(i).batch_id for i in ids}) == 1


@pytest.mark.parametrize(
    "description,age,count",
    [("in der Badewanne", 4, 1), ("braune Locken", 1, 1), ("braune Locken", 11, 1), ("x", 4, 0), ("x", 4, 13)],
)
def test_proposals_outside_the_rules_are_refused(tmp_path, signer, description, age, count):
    r = register(tmp_path, signer)
    with pytest.raises(RegisterError):
        r.propose(description, age, count, "Anna")
    assert r.all() == {}


def test_no_child_images_without_a_signer(tmp_path):
    r = register(tmp_path, None)
    with pytest.raises(RegisterError, match="signer"):
        r.propose("braune Locken", 4, 1, "Anna")
    assert r.all() == {} and not (tmp_path / "identities").exists()


def test_blocked_candidate_is_not_stored_and_cannot_be_endorsed(tmp_path, signer):
    r = register(tmp_path, signer, gate=BlockAllGate())
    (identity_id,) = r.propose("braune Locken", 4, 1, "Anna")
    assert r.get(identity_id).versions[1].images == []
    assert r.get(identity_id).blocked_images == 1
    assert not (tmp_path / "identities").exists()
    with pytest.raises(RegisterError, match="safety gate"):
        r.endorse(identity_id, "Anna")


# -- 2. four eyes ------------------------------------------------------------


def test_selection_needs_two_different_people(tmp_path, signer):
    r = register(tmp_path, signer)
    (identity_id,) = r.propose("braune Locken", 4, 1, "Anna")
    assert r.endorse(identity_id, "Anna") is IdentityStatus.CANDIDATE
    for same in ("Anna", " anna "):
        with pytest.raises(RegisterError, match="different person"):
            r.endorse(identity_id, same)
    assert r.endorse(identity_id, "Ben") is IdentityStatus.SELECTED
    assert r.get(identity_id).endorsed_by == ["Anna", "Ben"]
    with pytest.raises(RegisterError):
        r.endorse(identity_id, "Clara")


def test_rejected_candidate_is_out(tmp_path, signer):
    r = register(tmp_path, signer)
    (identity_id,) = r.propose("braune Locken", 4, 1, "Anna")
    r.reject(identity_id, "Anna", "passt nicht")
    with pytest.raises(RegisterError):
        r.endorse(identity_id, "Ben")
    with pytest.raises(RegisterError):
        r.extend_dataset(identity_id, 1)


# -- 3 to 6: training set, training, freeze ----------------------------------


def test_unselected_candidate_cannot_get_a_training_set(tmp_path, signer):
    r = register(tmp_path, signer)
    (identity_id,) = r.propose("braune Locken", 4, 1, "Anna")
    with pytest.raises(RegisterError, match="not been selected"):
        r.extend_dataset(identity_id, 1)


def test_training_set_is_generated_from_the_candidate_as_reference(tmp_path, signer):
    r, identity_id = selected(tmp_path, signer)
    images = r.extend_dataset(identity_id, 3)
    more = r.extend_dataset(identity_id, 2)
    assert len({image.pixels_sha256 for image in images + more}) == 5
    candidate = r.get(identity_id).versions[1].images[0]
    manifests = [e.payload["manifest"] for e in r.log.verify() if e.event == "identity_image"]
    assert all(m["request_sha256"] for m in manifests)
    assert r.get(identity_id).versions[1].images[1].role == "dataset"
    assert candidate.role == "candidate"


def test_training_set_needs_enough_images_and_approval(tmp_path, signer):
    r, identity_id = selected(tmp_path, signer)
    images = r.extend_dataset(identity_id, 8)
    with pytest.raises(RegisterError, match="at least 8"):
        r.approve_dataset(identity_id, "Anna", exclude=(images[0].sha256,))
    with pytest.raises(RegisterError, match="no approved training set"):
        r.train(identity_id, "Anna")
    with pytest.raises(RegisterError, match="unknown images"):
        r.approve_dataset(identity_id, "Anna", exclude=("nope",))
    r.extend_dataset(identity_id, 1)
    chosen = r.approve_dataset(identity_id, "Anna", exclude=(images[0].sha256,))
    assert len(chosen) == 8 and images[0].sha256 not in chosen
    assert not r.image_path(identity_id, images[0].sha256).exists()
    with pytest.raises(RegisterError, match="no longer a draft"):
        r.extend_dataset(identity_id, 1)


def test_changed_or_foreign_image_stops_approval_and_training(tmp_path, signer):
    r, identity_id = selected(tmp_path, signer)
    images = r.extend_dataset(identity_id, 8)
    path = r.image_path(identity_id, images[2].sha256)
    original = path.read_bytes()

    Image.new("RGB", (96, 96), (9, 9, 9)).save(path)  # a foreign picture under the same name
    with pytest.raises(RegisterError, match="changed on disk"):
        r.approve_dataset(identity_id, "Anna")

    path.write_bytes(original)
    r.approve_dataset(identity_id, "Anna")
    path.unlink()
    with pytest.raises(RegisterError, match="missing"):
        r.train(identity_id, "Anna")
    assert r.get(identity_id).latest.stage is VersionStage.DATASET_APPROVED


def test_image_signed_for_another_child_is_refused(tmp_path, signer):
    r = register(tmp_path, signer)
    a, b = r.propose("braune Locken", 4, 2, "Anna")
    foreign = r.get(b).versions[1].images[0]
    target = r.image_path(a, foreign.sha256)
    target.write_bytes(r.image_path(b, foreign.sha256).read_bytes())
    with pytest.raises(RegisterError, match="valid signature"):
        r._load_verified(a, foreign.sha256)


def test_training_records_exactly_what_went_in(tmp_path, signer):
    seen = {}

    class Recorder(MockTrainer):
        def train(self, spec, images):
            seen["spec"], seen["count"] = spec, len(images)
            return super().train(spec, images)

    r = register(tmp_path, signer, trainer=Recorder())
    (identity_id,) = r.propose("braune Locken", 4, 1, "Anna")
    r.endorse(identity_id, "Anna")
    r.endorse(identity_id, "Ben")
    r.extend_dataset(identity_id, 8)
    chosen = r.approve_dataset(identity_id, "Anna")
    weights = r.train(identity_id, "Anna")

    assert seen["count"] == 8 and list(seen["spec"].dataset_sha256) == chosen
    version = r.get(identity_id).latest
    assert version.stage is VersionStage.TRAINED and version.lora_sha256 == weights
    trained = next(e.payload for e in r.log.verify() if e.event == "lora_trained")
    assert trained["spec"]["dataset_sha256"] == chosen and trained["trainer_production"] is False
    with pytest.raises(RegisterError):
        r.train(identity_id, "Anna")


def test_freeze_checks_the_weights_file(tmp_path, signer):
    r, identity_id = selected(tmp_path, signer)
    with pytest.raises(RegisterError, match="not trained"):
        r.freeze(identity_id, "Ben")
    r.extend_dataset(identity_id, 8)
    r.approve_dataset(identity_id, "Anna")
    r.train(identity_id, "Anna")
    r.lora_path(identity_id, 1).write_bytes(b"swapped")
    with pytest.raises(RegisterError, match="missing or changed"):
        r.freeze(identity_id, "Ben")


def test_training_needs_a_trainer(tmp_path, signer):
    r, identity_id = selected(tmp_path, signer)
    r2 = register(tmp_path, signer, trainer=None)
    with pytest.raises(RegisterError, match="no trainer"):
        r2.train(identity_id, "Anna")


# -- 7. pool and brand -------------------------------------------------------


def test_pool_then_exclusive_to_one_brand(tmp_path, signer):
    r, identity_id = frozen(tmp_path, signer)
    r.add_to_pool(identity_id, "Anna")
    assert r.get(identity_id).status is IdentityStatus.POOL
    r.assign(identity_id, BRAND, "Anna")
    identity = r.get(identity_id)
    assert (identity.status, identity.brand) == (IdentityStatus.EXCLUSIVE, BRAND)
    with pytest.raises(RegisterError):
        r.assign(identity_id, "Andere Marke", "Anna")
    with pytest.raises(RegisterError):
        r.add_to_pool(identity_id, "Anna")


def test_pool_needs_a_frozen_version(tmp_path, signer):
    r, identity_id = selected(tmp_path, signer)
    with pytest.raises(RegisterError, match="frozen"):
        r.add_to_pool(identity_id, "Anna")
    r.assign(identity_id, BRAND, "Anna")  # made for one client from the start
    assert r.get(identity_id).brand == BRAND


def test_retired_child_is_no_longer_usable(tmp_path, signer):
    r, identity_id = frozen(tmp_path, signer)
    r.assign(identity_id, BRAND, "Anna")
    r.retire(identity_id, "Anna", "Vertrag beendet")
    ok, reason, _ = r.resolve_for_shooting(identity_id, 1, brand=BRAND, age_years=4, engine="mock")
    assert not ok and "not assigned" in reason
    with pytest.raises(RegisterError):
        r.retire(identity_id, "Anna")
    with pytest.raises(RegisterError):
        r.grow(identity_id, 5, "Anna")


# -- 8. grow -----------------------------------------------------------------


def test_child_grows_into_a_new_version_derived_from_the_old(tmp_path, signer):
    r, identity_id = frozen(tmp_path, signer, age=4)
    r.assign(identity_id, BRAND, "Anna")
    for bad in (4, 3):
        with pytest.raises(RegisterError, match="above 4"):
            r.grow(identity_id, bad, "Anna")
    with pytest.raises(RegisterError, match="v1 range"):
        r.grow(identity_id, 11, "Anna")

    assert r.grow(identity_id, 6, "Anna") == 2
    with pytest.raises(RegisterError, match="must be frozen"):
        r.grow(identity_id, 7, "Anna")
    r.extend_dataset(identity_id, 8)
    r.approve_dataset(identity_id, "Anna")
    r.train(identity_id, "Anna")
    r.freeze(identity_id, "Ben")

    identity = r.get(identity_id)
    v1, v2 = identity.versions[1], identity.versions[2]
    assert (v2.age_years, v2.parent, v2.stage) == (6, 1, VersionStage.FROZEN)
    assert v1.stage is VersionStage.FROZEN and v1.lora_sha256 != v2.lora_sha256
    assert not set(v1.dataset) & set(v2.dataset)
    # Both ages stay usable, each with its own weights.
    for version, age in ((1, 4), (2, 6)):
        ok, _, ref = r.resolve_for_shooting(identity_id, version, brand=BRAND, age_years=age, engine="mock")
        assert ok and ref["lora_sha256"] == identity.versions[version].lora_sha256


# -- engines -----------------------------------------------------------------


def test_child_is_bound_to_its_engine(tmp_path, signer):
    from nps.engine.flux2_klein import Flux2KleinEngine

    r, identity_id = selected(tmp_path, signer)
    flux = register(tmp_path, signer, engine=Flux2KleinEngine(backend=FakeBackend()))
    with pytest.raises(RegisterError, match="belongs to engine 'mock'"):
        flux.extend_dataset(identity_id, 1)


def test_engine_without_reference_support_cannot_extend(tmp_path, signer):
    from nps.engine.flux2_klein import Flux2KleinEngine

    engine = Flux2KleinEngine(backend=FakeBackend())
    r = IdentityRegister(tmp_path, engine, AllowAll(), signer)
    (identity_id,) = r.propose("braune Locken", 4, 1, "Anna")
    r.endorse(identity_id, "Anna")
    r.endorse(identity_id, "Ben")
    with pytest.raises(RegisterError, match="reference images"):
        r.extend_dataset(identity_id, 1)


class AllowAll:
    name, production = "allow_all_test", False

    def evaluate(self, image, manifest):
        from nps.core.models import CheckResult

        return CheckResult(check="safety_gate", passed=True, details={"gate": self.name})


def test_inputs_must_match_the_request_hashes(tmp_path):
    image = Image.new("RGB", (8, 8), (1, 2, 3))
    request = GenerationRequest(prompt="p", seed=1, width=64, height=64, reference_sha256=("x",))
    with pytest.raises(ValueError):
        check_inputs(request, GenerationInputs(references=(image,)))
    with pytest.raises(ValueError):
        MockEngine().generate(request)
    plain = GenerationRequest(prompt="p", seed=1, width=64, height=64)
    with pytest.raises(ValueError):
        MockEngine().generate(plain, GenerationInputs(references=(image,)))


# -- use in a shooting -------------------------------------------------------


def shooting_setup(tmp_path, signer, **person):
    r, identity_id = frozen(tmp_path, signer, age=4)
    r.assign(identity_id, BRAND, "Anna")
    pipe = Pipeline(tmp_path, MockEngine(), MockOnlyGate(), log=r.log, upload_gate=open_upload_gate(), register=r)
    data = {"age_years": 4, "description": "spielt", "identity_id": identity_id, "identity_version": 1}
    data.update(person)
    return r, pipe, identity_id, make_brief(persons=[data])


def test_shooting_uses_the_childs_weights(tmp_path, signer, product):
    r, pipe, identity_id, brief = shooting_setup(tmp_path, signer)
    records = pipe.generate_variants(brief, product, "m1", count=2)
    assert all(record.state is AssetState.IN_REVIEW for record in records)
    lora = r.get(identity_id).versions[1].lora_sha256
    shooting = pipe.state(brief.campaign_id).shootings[brief.shooting_id]
    assert shooting.identities == [{"identity_id": identity_id, "version": 1, "lora_sha256": lora}]

    plain = Pipeline(tmp_path / "plain", MockEngine(), MockOnlyGate(), upload_gate=open_upload_gate())
    no_child = make_brief()
    other = plain.generate_variants(no_child, product, "m1", count=1)
    with_child = pipe.state(brief.campaign_id).assets[records[0].asset_id].manifest
    without = plain.state(no_child.campaign_id).assets[other[0].asset_id].manifest
    assert with_child["request_sha256"] != without["request_sha256"]

    dossier = build_dossier(pipe.log, brief.campaign_id)
    (identity,) = dossier["shootings"][0]["identities"]
    assert identity["selected_by"] == ["Anna", "Ben"] and identity["brand"] == BRAND
    assert identity["versions"][0]["dataset_approved_by"] == "Anna"
    assert len(identity["versions"][0]["dataset"]) == 8


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"identity_id": "id-unknown"}, "unknown identity"),
        ({"identity_version": 2}, "not frozen"),
        ({"age_years": 5}, "is 4 years old"),
    ],
)
def test_brief_with_unusable_child_is_rejected(tmp_path, signer, product, change, expected):
    _, pipe, _, brief = shooting_setup(tmp_path, signer, **change)
    (record,) = pipe.generate_shooting(brief, product)
    assert record.state is AssetState.REJECTED
    assert expected in record.checks[0].details["reasons"][0]
    assert pipe.state(brief.campaign_id).shootings == {}


def test_child_of_another_brand_cannot_be_used(tmp_path, signer, product):
    _, pipe, _, brief = shooting_setup(tmp_path, signer)
    foreign = make_brief(persons=brief.model_dump()["persons"], brand={"name": "Andere Marke"})
    (record,) = pipe.generate_shooting(foreign, product)
    assert "not assigned to brand 'Andere Marke'" in record.checks[0].details["reasons"][0]


def test_brief_naming_a_child_needs_a_register(tmp_path, signer, product):
    _, _, _, brief = shooting_setup(tmp_path, signer)
    bare = Pipeline(tmp_path / "bare", MockEngine(), MockOnlyGate(), upload_gate=open_upload_gate())
    (record,) = bare.generate_shooting(brief, product)
    assert "no register is configured" in record.checks[0].details["reasons"][0]


def test_weights_changed_after_registration_stop_generation(tmp_path, signer, product):
    r, pipe, identity_id, brief = shooting_setup(tmp_path, signer)
    pipe.generate_variants(brief, product, "m1", count=1)
    r.lora_path(identity_id, 1).write_bytes(b"swapped")
    with pytest.raises(PipelineError, match="missing or changed"):
        pipe.generate_variants(brief, product, "m1", count=1)


def test_identity_fields_come_as_a_pair():
    with pytest.raises(ValueError, match="together"):
        make_brief(persons=[{"age_years": 4, "description": "x", "identity_id": "id-1"}])


def test_cli_walks_a_child_from_proposal_to_brand(tmp_path, monkeypatch, capsys):
    from nps.cli import main

    assert main(["dev-cert", "--out", str(tmp_path / "certs")]) == 0
    monkeypatch.setenv("NPS_C2PA_CERT", str(tmp_path / "certs" / "dev-chain.pem"))
    monkeypatch.setenv("NPS_C2PA_KEY", str(tmp_path / "certs" / "dev-key.pem"))
    out = str(tmp_path / "work")
    base = ["--out", out, "--safety-gate", "mock_only"]

    def run(*args):
        capsys.readouterr()
        code = main(["identity", *args])
        return code, capsys.readouterr()

    code, io_ = run("propose", *base, "--description", "braune Locken", "--age", "4", "--count", "2", "--by", "Anna")
    assert code == 0
    identity_id = io_.out.split(":")[0]
    assert run("endorse", *base, "--id", identity_id, "--by", "Anna")[0] == 0
    assert run("endorse", *base, "--id", identity_id, "--by", "Anna")[0] == 1
    assert run("endorse", *base, "--id", identity_id, "--by", "Ben")[0] == 0
    assert run("extend", *base, "--id", identity_id, "--count", "8")[0] == 0
    assert run("approve", *base, "--id", identity_id, "--by", "Anna")[0] == 0
    assert run("train", *base, "--id", identity_id, "--by", "Anna")[0] == 1  # no trainer chosen
    assert run("train", *base, "--id", identity_id, "--by", "Anna", "--trainer", "mock")[0] == 0
    assert run("freeze", *base, "--id", identity_id, "--by", "Ben")[0] == 0
    assert run("pool", *base, "--id", identity_id, "--by", "Anna")[0] == 0
    assert run("assign", *base, "--id", identity_id, "--by", "Anna", "--brand", "Testmarke")[0] == 0
    assert run("grow", *base, "--id", identity_id, "--by", "Anna", "--age", "6")[0] == 0
    code, io_ = run("list", "--out", out)
    assert "exclusive, Marke Testmarke" in io_.out
    assert "Version 2: 6 Jahre, draft" in io_.out
    assert main(["verify", "--out", out]) == 0
