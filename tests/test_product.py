import pytest
from PIL import Image

from nps.core.models import Placement
from nps.product.composite import PlacementError, composite_product, verify_product_pixels

AT = Placement(x=20, y=30)


def scene():
    return Image.new("RGB", (200, 150), (240, 240, 240))


def test_composited_product_passes(product):
    result = verify_product_pixels(composite_product(scene(), product, AT), product, AT)
    assert result.passed
    assert result.details["core_pixels"] == 48 * 28
    assert result.details["mismatched_pixels"] == 0
    assert result.details["edge_pixels"] > 0


def test_scene_outside_the_product_is_untouched(product):
    composed = composite_product(scene(), product, AT)
    assert composed.getpixel((0, 0)) == (240, 240, 240)
    assert composed.getpixel((199, 149)) == (240, 240, 240)


def test_single_changed_core_pixel_fails(product):
    composed = composite_product(scene(), product, AT)
    x, y = AT.x + 10, AT.y + 10
    r, g, b = composed.getpixel((x, y))
    composed.putpixel((x, y), (r, g, b ^ 1))
    result = verify_product_pixels(composed, product, AT)
    assert not result.passed
    assert result.details["mismatched_pixels"] == 1


def test_changed_edge_pixel_does_not_fail(product):
    composed = composite_product(scene(), product, AT)
    composed.putpixel((AT.x + 3, AT.y + 3), (0, 0, 0))
    assert verify_product_pixels(composed, product, AT).passed


def test_wrong_position_fails(product):
    composed = composite_product(scene(), product, AT)
    assert not verify_product_pixels(composed, product, Placement(x=21, y=30)).passed


def test_product_without_opaque_pixels_cannot_pass():
    ghost = Image.new("RGBA", (10, 10), (255, 0, 0, 100))
    composed = composite_product(scene(), ghost, AT)
    assert not verify_product_pixels(composed, ghost, AT).passed


def test_product_must_fit_and_have_alpha(product):
    with pytest.raises(PlacementError):
        composite_product(scene(), product, Placement(x=150, y=30))
    with pytest.raises(PlacementError):
        composite_product(scene(), product.convert("RGB"), AT)
