import pytest
from PIL import Image

from nps.detectors import FREEPIK, ModelError, PinnedModel
from nps.engine.mock import MockEngine
from nps.pipeline import Pipeline
from nps.safety.gate import gate_by_name
from nps.safety.provisional import ProvisionalGate
from nps.state import NOTICE_PLACEHOLDER_GATE, NOTICE_PROVISIONAL_GATE
from tests.fakes import open_upload_gate

IMAGE = Image.new("RGB", (64, 64), (100, 100, 100))


class Fixed:
    def __init__(self, name, scores=None, fail=False):
        self.name, self._scores, self._fail = name, scores, fail

    def scores(self, image):
        if self._fail:
            raise RuntimeError("model broken")
        return self._scores


def gate(neutral=0.99, nsfw=0.05, **kwargs):
    primary = kwargs.get("primary") or Fixed("freepik", {"neutral": neutral, "low": 1 - neutral})
    second = kwargs.get("second") or Fixed("marqo", {"NSFW": nsfw, "SFW": 1 - nsfw})
    return ProvisionalGate(primary, second)


def test_clearly_neutral_image_passes():
    result = gate().evaluate(IMAGE, None)
    assert result.passed and result.details["reasons"] == []
    assert result.details["scores"]["freepik"]["neutral"] == 0.99
    assert result.details["models"]["freepik"]["revision"] == FREEPIK.revision


@pytest.mark.parametrize("neutral,nsfw", [(0.89, 0.05), (0.99, 0.31), (0.5, 0.9)])
def test_either_classifier_can_block(neutral, nsfw):
    assert not gate(neutral, nsfw).evaluate(IMAGE, None).passed


def test_both_reasons_are_reported():
    assert len(gate(0.5, 0.9).evaluate(IMAGE, None).details["reasons"]) == 2


def test_thresholds_are_inclusive_on_the_safe_side():
    assert gate(0.90, 0.30).evaluate(IMAGE, None).passed


@pytest.mark.parametrize("which", ["primary", "second"])
def test_failing_classifier_blocks(which):
    result = gate(**{which: Fixed("x", fail=True)}).evaluate(IMAGE, None)
    assert not result.passed and "classifier failed" in result.details["reasons"][0]


def test_missing_or_broken_scores_block():
    assert not gate(primary=Fixed("freepik", {})).evaluate(IMAGE, None).passed
    assert not gate(second=Fixed("marqo", {})).evaluate(IMAGE, None).passed
    nan = float("nan")
    assert not gate(primary=Fixed("freepik", {"neutral": nan})).evaluate(IMAGE, None).passed
    assert not gate(second=Fixed("marqo", {"NSFW": nan})).evaluate(IMAGE, None).passed


def test_gate_is_marked_provisional_everywhere(tmp_path, brief, product):
    assert ProvisionalGate.production is False
    assert gate_by_name("provisional").name == "provisional"
    pipe = Pipeline(tmp_path, MockEngine(), gate(), upload_gate=open_upload_gate())
    pipe.generate_variants(brief, product, "m1", count=1)
    notices = pipe.state(brief.campaign_id).notices
    assert NOTICE_PROVISIONAL_GATE in notices and NOTICE_PLACEHOLDER_GATE not in notices


def test_blocking_gate_keeps_the_image_off_disk(tmp_path, brief, product):
    pipe = Pipeline(tmp_path, MockEngine(), gate(neutral=0.2), upload_gate=open_upload_gate())
    (record,) = pipe.generate_variants(brief, product, "m1", count=1)
    assert record.state.value == "blocked"
    assert not (tmp_path / "assets").exists()
    stored = pipe.state(brief.campaign_id).assets[record.asset_id].checks[-1]
    assert stored["details"]["scores"]["freepik"]["neutral"] == 0.2


def test_pinned_files_must_exist_and_match(tmp_path):
    import hashlib

    good = hashlib.sha256(b"weights").hexdigest()
    model = PinnedModel("m", "org/repo", "rev", "MIT", {"w.bin": good})
    with pytest.raises(ModelError, match="missing"):
        model.verify(tmp_path)
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "w.bin").write_bytes(b"other")
    with pytest.raises(ModelError, match="checksum"):
        model.verify(tmp_path)
    (tmp_path / "m" / "w.bin").write_bytes(b"weights")
    assert model.verify(tmp_path) == tmp_path / "m"
    assert model.url("w.bin") == "https://huggingface.co/org/repo/resolve/rev/w.bin"


def test_real_gate_blocks_when_models_are_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("NPS_MODELS_DIR", str(tmp_path / "none"))
    result = ProvisionalGate().evaluate(IMAGE, None)
    assert not result.passed and "classifier failed" in result.details["reasons"][0]
