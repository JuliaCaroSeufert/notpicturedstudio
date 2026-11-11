import pytest
from PIL import Image, ImageDraw

from nps.core.models import Brief


def make_brief(**overrides) -> Brief:
    data = {
        "campaign_id": "test-campaign",
        "brand": {"name": "Testmarke", "colors": ["#112233"]},
        "product_name": "Holzbauklötze",
        "product_category": "toys",
        "scene": "Helles Kinderzimmer mit Holzboden",
        "child": {"age_years": 4, "description": "stapelt Klötze"},
        "width": 256,
        "height": 256,
        "seed": 7,
        "placement": {"x": 20, "y": 30},
    }
    data.update(overrides)
    return Brief.model_validate(data)


@pytest.fixture
def brief() -> Brief:
    return make_brief()


@pytest.fixture
def product() -> Image.Image:
    """Opaque core with a half-transparent rim, like a real cut-out."""
    image = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 57, 37), fill=(200, 30, 30, 128))
    draw.rectangle((6, 6, 53, 33), fill=(10, 120, 200, 255))
    return image
