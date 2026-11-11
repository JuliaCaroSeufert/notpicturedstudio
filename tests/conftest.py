import pytest
from PIL import Image, ImageDraw

from nps.core.models import ShootingBrief


def make_brief(**overrides) -> ShootingBrief:
    data = {
        "campaign_id": "test-campaign",
        "shooting_id": "shooting-a",
        "brand": {"name": "Testmarke", "colors": ["#112233"]},
        "product_name": "Holzbauklötze",
        "product_category": "toys",
        "scene": "Helles Kinderzimmer mit Holzboden",
        "persons": [{"age_years": 4, "description": "stapelt Klötze"}],
        "width": 128,
        "height": 128,
        "base_seed": 7,
        "motifs": [
            {"motif_id": "m1", "description": "Kind stapelt", "placement": {"x": 20, "y": 30}},
            {"motif_id": "m2", "placement": {"x": 60, "y": 10}},
        ],
    }
    data.update(overrides)
    return ShootingBrief.model_validate(data)


def with_person(**person) -> ShootingBrief:
    return make_brief(persons=[{"age_years": 4, "description": "spielt", **person}])


@pytest.fixture
def brief() -> ShootingBrief:
    return make_brief()


@pytest.fixture
def product() -> Image.Image:
    """Opaque core with a half-transparent rim, like a real cut-out."""
    image = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 57, 37), fill=(200, 30, 30, 128))
    draw.rectangle((6, 6, 53, 33), fill=(10, 120, 200, 255))
    return image
