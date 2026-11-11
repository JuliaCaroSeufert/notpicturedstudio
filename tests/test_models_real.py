"""Runs the real detection models. Skipped where they are not installed.

Install them with `python scripts/fetch_models.py`. Only harmless generated
images are used here; how the classifiers react to unsafe content is not
covered by these tests.
"""

import pytest
from PIL import Image, ImageDraw

from nps.cli import demo_product
from nps.detectors import ALL_MODELS, ModelError, models_dir
from nps.engine.base import GenerationRequest
from nps.engine.mock import MockEngine
from nps.intake.upload import DetectorUploadGate, UploadDecision
from nps.safety.provisional import ProvisionalGate


def _installed() -> bool:
    try:
        for model in ALL_MODELS:
            model.verify(models_dir())
        return True
    except ModelError:
        return False


pytestmark = pytest.mark.skipif(not _installed(), reason="detection models not installed")


def still_life() -> Image.Image:
    image = Image.new("RGB", (640, 480), (236, 228, 214))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 330, 640, 480), fill=(181, 142, 99))
    draw.rectangle((220, 250, 300, 330), fill=(214, 64, 69))
    draw.rectangle((300, 210, 400, 330), fill=(31, 111, 139))
    draw.ellipse((330, 130, 410, 210), fill=(242, 193, 78))
    return image


def test_safety_gate_passes_a_harmless_still_life():
    result = ProvisionalGate().evaluate(still_life(), None)
    assert result.passed, result.details
    assert set(result.details["scores"]) == {"freepik", "marqo"}


def test_second_classifier_is_noisy_on_abstract_graphics():
    """Documents a measured weakness instead of hiding it.

    On the mock engine's flat colour blocks the main classifier is certain the
    image is neutral, while the small second one drifts up to roughly 0.5. The
    gate then blocks, which is the safe direction. Real photos score around
    0.05. The threshold must be calibrated on real generated images.
    """
    gate = ProvisionalGate()
    scores = []
    for seed in range(1, 7):
        request = GenerationRequest(prompt="p", seed=seed, width=512, height=512)
        details = gate.evaluate(MockEngine().generate(request).image, None).details
        assert details["scores"]["freepik"]["neutral"] > 0.99
        scores.append(details["scores"]["marqo"]["NSFW"])
    assert max(scores) < 0.6 and max(scores) > 0.2


def test_upload_gate_accepts_images_without_people():
    gate = DetectorUploadGate()
    for image in (still_life(), demo_product()):
        verdict = gate.check_image(image)
        assert verdict.decision is UploadDecision.ACCEPTED, verdict
