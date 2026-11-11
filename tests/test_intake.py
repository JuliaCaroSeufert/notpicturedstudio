import pytest

from nps.intake.brief import screen_brief
from tests.conftest import make_brief, with_person


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
    assert not screen_brief(with_person(description="trägt nur eine Windel")).passed
    motifs = [{"motif_id": "m1", "description": "Kind in der Badewanne", "placement": {"x": 0, "y": 0}}]
    result = screen_brief(make_brief(motifs=motifs))
    assert not result.passed
    assert "motif 'm1'" in result.details["reasons"][0]


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


@pytest.mark.parametrize("age", [2, 6, 10])
def test_ages_in_the_v1_range_pass(age):
    assert screen_brief(with_person(age_years=age)).passed


@pytest.mark.parametrize("age", [0, 1, 11, 17])
def test_ages_outside_the_v1_range_are_rejected(age):
    result = screen_brief(with_person(age_years=age))
    assert not result.passed
    assert "outside the v1 range" in result.details["reasons"][0]


def test_adult_age_is_not_a_valid_person_yet():
    with pytest.raises(ValueError):
        with_person(age_years=18)


def test_more_than_one_person_is_rejected_in_v1():
    persons = [{"age_years": 4, "description": "spielt"}, {"age_years": 6, "description": "liest"}]
    result = screen_brief(make_brief(persons=persons))
    assert not result.passed
    assert "exactly one child" in result.details["reasons"][0]


def test_brief_shape_rules():
    placement = {"x": 0, "y": 0}
    with pytest.raises(ValueError, match="unique"):
        make_brief(motifs=[{"motif_id": "m1", "placement": placement}] * 2)
    with pytest.raises(ValueError):
        make_brief(motifs=[])
    with pytest.raises(ValueError):
        make_brief(variants_per_motif=5)
