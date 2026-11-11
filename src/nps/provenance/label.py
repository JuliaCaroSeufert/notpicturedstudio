"""Visible AI label. C2PA and the invisible watermark follow in a later step."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

LABEL_TEXT = "KI-generiert"


class LabelError(ValueError):
    """No corner is free of the protected product area."""


def _intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def apply_visible_label(
    image: Image.Image,
    protected_box: tuple[int, int, int, int],
    text: str = LABEL_TEXT,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Draw the label in the first corner that does not touch the product."""
    font_size = max(12, image.height // 40)
    font = ImageFont.load_default(size=font_size)
    pad = font_size // 2
    left, top, right, bottom = font.getbbox(text)
    box_w, box_h = (right - left) + 2 * pad, (bottom - top) + 2 * pad
    margin = pad

    corners = [
        (image.width - box_w - margin, image.height - box_h - margin),
        (margin, image.height - box_h - margin),
        (image.width - box_w - margin, margin),
        (margin, margin),
    ]
    for x, y in corners:
        box = (x, y, x + box_w, y + box_h)
        if x >= 0 and y >= 0 and not _intersects(box, protected_box):
            result = image.convert("RGB")
            draw = ImageDraw.Draw(result)
            # Pillow includes the far edge, the box does not.
            draw.rectangle((x, y, x + box_w - 1, y + box_h - 1), fill=(0, 0, 0))
            draw.text((x + pad - left, y + pad - top), text, font=font, fill=(255, 255, 255))
            return result, box
    raise LabelError("no corner is free for the visible label without covering the product")
