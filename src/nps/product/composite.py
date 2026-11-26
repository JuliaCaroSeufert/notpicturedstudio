"""Product fidelity: the real product is pasted, never redrawn.

The product is placed at its native resolution. Fully opaque product pixels are
the protected core and must survive unchanged into the final file; partially
transparent edge pixels are blended and reported separately.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from nps.core.models import CheckResult, Placement


class PlacementError(ValueError):
    """The product does not fit into the scene at the requested position."""


def _require_fit(scene_size: tuple[int, int], product: Image.Image, placement: Placement) -> None:
    if product.mode != "RGBA":
        raise PlacementError("product image must be RGBA (cut-out with alpha channel)")
    width, height = scene_size
    if placement.x + product.width > width or placement.y + product.height > height:
        raise PlacementError(
            f"product {product.width}x{product.height} at ({placement.x},{placement.y}) "
            f"does not fit into scene {width}x{height}"
        )


def product_box(product: Image.Image, placement: Placement) -> tuple[int, int, int, int]:
    return (placement.x, placement.y, placement.x + product.width, placement.y + product.height)


# Neutral grey behind the product; the model repaints all of it.
CANVAS_FILL = (128, 128, 128)
# The mask keeps the product minus this rim, so the model can blend the edge.
EDGE_RIM_PX = 2


def product_canvas(
    size: tuple[int, int], product: Image.Image, placement: Placement
) -> tuple[Image.Image, Image.Image]:
    """Canvas and mask for painting a scene around the product.

    The model sees the product where it will end up and paints room, light and
    shadow around it, so size and position fit together. White in the mask means
    "paint here". The real pixels are pasted again afterwards; the canvas only
    tells the model what stands where.
    """
    _require_fit(size, product, placement)
    canvas = Image.new("RGB", size, CANVAS_FILL)
    canvas.paste(product, (placement.x, placement.y), mask=product.getchannel("A"))
    keep = Image.new("L", size, 0)
    keep.paste(product.getchannel("A").point(lambda a: 255 if a == 255 else 0), (placement.x, placement.y))
    keep = keep.filter(ImageFilter.MinFilter(2 * EDGE_RIM_PX + 1))
    return canvas, keep.point(lambda v: 255 - v)


def composite_product(scene: Image.Image, product: Image.Image, placement: Placement) -> Image.Image:
    _require_fit(scene.size, product, placement)
    result = scene.convert("RGB")
    result.paste(product, (placement.x, placement.y), mask=product.getchannel("A"))
    return result


def verify_product_pixels(
    image: Image.Image, product: Image.Image, placement: Placement
) -> CheckResult:
    """Compare every fully opaque product pixel with the same pixel in the image."""
    _require_fit(image.size, product, placement)
    source = np.asarray(product)
    region = np.asarray(image.convert("RGB").crop(product_box(product, placement)))
    core = source[..., 3] == 255
    core_pixels = int(core.sum())
    mismatched = int((np.any(region != source[..., :3], axis=-1) & core).sum())
    return CheckResult(
        check="product_pixel_fidelity",
        # A product without any opaque pixel cannot be verified, so it fails.
        passed=core_pixels > 0 and mismatched == 0,
        details={
            "core_pixels": core_pixels,
            "mismatched_pixels": mismatched,
            "edge_pixels": int(((source[..., 3] > 0) & ~core).sum()),
        },
    )
