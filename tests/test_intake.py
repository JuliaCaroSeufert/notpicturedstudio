import pytest

from nps.intake.brief import screen_brief
from tests.conftest import make_brief


def test_ordinary_brief_passes(brief):
    assert screen_brief(brief).passed


@pytest.mark.parametrize("category", ["diapers", "bath", "swimwear", "underwear"])
def test_excluded_categories_are_rejected(category):
    result = screen_brief(make_brief(product_category=category))
    assert not result.passed
    assert category in result.details["reasons"][0]


@pytest.mark.parametrize(
    "scene",
    [
        "Baby in der Badewanne",
        "Kind spielt im Bad",
        "Kleinkind mit Schwimmwindel am See",
        "toddler at the pool",
        "baby on the changing table wearing only a diaper",
        "Kind am Strand",
        "Kind nackt auf der Decke",
        "child in underwear",
        "Baby auf dem Wickeltisch",
        "BABY IN THE BATHTUB",
    ],
)
def test_excluded_contexts_in_the_scene_are_rejected(scene):
    assert not screen_brief(make_brief(scene=scene)).passed


def test_excluded_terms_are_found_in_every_text_field():
    assert not screen_brief(make_brief(product_name="Stoffwindeln")).passed
    assert not screen_brief(
        make_brief(child={"age_group": "infant", "description": "trägt nur eine Windel"})
    ).passed


@pytest.mark.parametrize(
    "scene",
    [
        "Kind entwickelt ein Bauwerk aus Klötzen",
        "Familie fährt im Carpool zur Kita",
        "Kind mit Badminton-Schläger im Garten",
    ],
)
def test_harmless_lookalikes_pass(scene):
    assert screen_brief(make_brief(scene=scene)).passed
