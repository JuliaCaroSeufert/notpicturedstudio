import numpy as np
import pytest
from PIL import Image

from nps.core.models import Placement
from nps.product.composite import (
    CANVAS_FILL,
    EDGE_RIM_PX,
    PlacementError,
    composite_product,
    product_canvas,
    verify_product_pixels,
)

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


# -- scene around the product ----------------------------------------------------


def test_canvas_shows_the_product_where_it_will_end_up(product):
    canvas, mask = product_canvas((200, 150), product, AT)
    assert canvas.size == mask.size == (200, 150)
    assert verify_product_pixels(canvas, product, AT).passed
    assert canvas.getpixel((0, 0)) == CANVAS_FILL


def test_mask_keeps_the_product_core_and_frees_its_rim(product):
    _, mask = product_canvas((200, 150), product, AT)
    # Opaque core of the fixture: x 6..53, y 6..33; minus a rim of EDGE_RIM_PX.
    r = EDGE_RIM_PX
    assert mask.getpixel((AT.x + 6 + r, AT.y + 6 + r)) == 0
    assert mask.getpixel((AT.x + 53 - r, AT.y + 33 - r)) == 0
    assert mask.getpixel((AT.x + 6 + r - 1, AT.y + 20)) == 255  # rim: repainted
    assert mask.getpixel((AT.x + 3, AT.y + 3)) == 255  # half-transparent edge
    assert mask.getpixel((0, 0)) == 255  # scene
    assert set(np.unique(np.asarray(mask))) == {0, 255}


def test_canvas_needs_a_fitting_cut_out(product):
    with pytest.raises(PlacementError):
        product_canvas((70, 60), product, AT)
