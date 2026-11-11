from nps.core.hashing import sha256_image
from nps.engine.base import Capability, GenerationRequest
from nps.engine.mock import MockEngine


def request(**overrides):
    data = {"prompt": "Kinderzimmer", "seed": 1, "width": 96, "height": 64}
    data.update(overrides)
    return GenerationRequest(**data)


def test_same_request_gives_identical_image():
    engine = MockEngine()
    first, second = engine.generate(request()), engine.generate(request())
    assert first.image.tobytes() == second.image.tobytes()
    assert first.manifest == second.manifest


def test_seed_and_prompt_change_the_image():
    engine = MockEngine()
    base = engine.generate(request()).manifest.output_sha256
    assert engine.generate(request(seed=2)).manifest.output_sha256 != base
    assert engine.generate(request(prompt="Garten")).manifest.output_sha256 != base


def test_manifest_describes_the_output():
    result = MockEngine().generate(request())
    assert result.image.size == (96, 64)
    assert result.image.mode == "RGB"
    assert result.manifest.output_sha256 == sha256_image(result.image)
    assert result.manifest.engine == "mock"
    assert result.manifest.seed == 1


def test_mock_engine_is_marked_as_non_production():
    engine = MockEngine()
    assert engine.describe().production is False
    assert engine.capabilities() == {Capability.TEXT2IMG}
