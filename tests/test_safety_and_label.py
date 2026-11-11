import pytest
from PIL import Image

from nps.engine.base import GenerationRequest
from nps.engine.mock import MockEngine
from nps.provenance.label import LabelError, apply_visible_label
from nps.safety.gate import BlockAllGate, MockOnlyGate, gate_by_name


def mock_result():
    return MockEngine().generate(GenerationRequest(prompt="p", seed=1, width=64, height=64))


def test_default_gate_blocks_everything():
    result = mock_result()
    assert not BlockAllGate().evaluate(result.image, result.manifest).passed


def test_mock_gate_passes_only_the_mock_engine():
    result = mock_result()
    gate = MockOnlyGate()
    assert gate.evaluate(result.image, result.manifest).passed
    other = result.manifest.model_copy(update={"engine": "flux2-klein-4b"})
    assert not gate.evaluate(result.image, other).passed


def test_no_step0_gate_claims_to_be_production():
    assert BlockAllGate.production is False
    assert MockOnlyGate.production is False


def test_unknown_gate_name_is_an_error():
    with pytest.raises(ValueError):
        gate_by_name("allow_all")


def test_label_changes_only_its_own_box():
    image = Image.new("RGB", (400, 400), (200, 200, 200))
    labelled, box = apply_visible_label(image, (0, 0, 50, 50))
    assert labelled.getpixel((box[0] + 1, box[1] + 1)) == (0, 0, 0)
    outside = labelled.copy()
    outside.paste((200, 200, 200), box)
    assert outside.tobytes() == image.tobytes()
    assert any(color == (255, 255, 255) for _, color in labelled.crop(box).getcolors(maxcolors=100000))


def test_label_moves_away_from_the_product():
    image = Image.new("RGB", (400, 400), (200, 200, 200))
    _, default_box = apply_visible_label(image, (0, 0, 10, 10))
    _, moved_box = apply_visible_label(image, default_box)
    assert moved_box != default_box


def test_label_refuses_to_cover_the_product():
    image = Image.new("RGB", (400, 400), (200, 200, 200))
    with pytest.raises(LabelError):
        apply_visible_label(image, (0, 0, 400, 400))
