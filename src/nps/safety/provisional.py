"""Provisional safety gate: two general nudity classifiers, strict thresholds.

This is not a child-safety classifier. It stays marked as non-production until
a dedicated classifier (Thorn) is connected. Every generated image in this
system shows a child, so any nudity signal blocks; no age estimate is involved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from nps.core.models import CheckResult, Manifest
from nps.detectors import FREEPIK, MARQO, PinnedModel, models_dir

# Freepik: block unless the image is clearly "neutral".
FREEPIK_MIN_NEUTRAL = 0.90
# Marqo: block well below the usual 0.5 decision point.
MARQO_MAX_NSFW = 0.30


class Classifier(Protocol):
    name: str

    def scores(self, image: Image.Image) -> dict[str, float]: ...


class TimmClassifier:
    """Image classifier in timm format, loaded from a pinned local folder."""

    def __init__(self, model: PinnedModel, directory: Path | None = None) -> None:
        self.name = model.key
        self._pinned = model
        self._directory = directory
        self._loaded: Any = None

    def _load(self) -> Any:
        if self._loaded is None:
            import timm
            import torch
            from safetensors.torch import load_file

            folder = self._pinned.verify(self._directory or models_dir())
            config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
            net = timm.create_model(
                config["architecture"], pretrained=False, num_classes=config["num_classes"]
            )
            weights = load_file(folder / "model.safetensors")
            # strict=True: a partly loaded network would give meaningless scores.
            net.load_state_dict(weights, strict=True)
            net.eval()
            self._loaded = (torch, net, config["label_names"], config["pretrained_cfg"])
        return self._loaded

    def scores(self, image: Image.Image) -> dict[str, float]:
        torch, net, labels, cfg = self._load()
        size = cfg["input_size"][1]
        pixels = np.asarray(
            image.convert("RGB").resize((size, size), Image.Resampling.BICUBIC), dtype=np.float32
        )
        pixels = (pixels / 255.0 - np.array(cfg["mean"], dtype=np.float32)) / np.array(
            cfg["std"], dtype=np.float32
        )
        with torch.no_grad():
            logits = net(torch.from_numpy(pixels.transpose(2, 0, 1))[None].float())
            probabilities = torch.softmax(logits, dim=-1)[0].tolist()
        return {label: float(p) for label, p in zip(labels, probabilities)}


class ProvisionalGate:
    name = "provisional"
    production = False

    def __init__(
        self,
        primary: Classifier | None = None,
        second: Classifier | None = None,
        *,
        min_neutral: float = FREEPIK_MIN_NEUTRAL,
        max_nsfw: float = MARQO_MAX_NSFW,
    ) -> None:
        self._primary = primary or TimmClassifier(FREEPIK)
        self._second = second or TimmClassifier(MARQO)
        self._min_neutral = min_neutral
        self._max_nsfw = max_nsfw

    def evaluate(self, image: Image.Image, manifest: Manifest) -> CheckResult:
        details: dict[str, Any] = {
            "gate": self.name,
            "thresholds": {"min_neutral": self._min_neutral, "max_nsfw": self._max_nsfw},
            "models": {FREEPIK.key: FREEPIK.identity(), MARQO.key: MARQO.identity()},
        }
        reasons: list[str] = []
        try:
            primary = self._primary.scores(image)
            second = self._second.scores(image)
            details["scores"] = {
                self._primary.name: {k: round(v, 4) for k, v in primary.items()},
                self._second.name: {k: round(v, 4) for k, v in second.items()},
            }
            # A missing label counts as the unsafe value, never as a pass.
            neutral = primary.get("neutral", 0.0)
            nsfw = second.get("NSFW", 1.0)
            if not neutral >= self._min_neutral:
                reasons.append(f"{self._primary.name}: neutral {neutral:.3f} below {self._min_neutral}")
            if not nsfw <= self._max_nsfw:
                reasons.append(f"{self._second.name}: NSFW {nsfw:.3f} above {self._max_nsfw}")
        except Exception as error:  # noqa: BLE001 - any failure must block, not crash through
            reasons.append(f"classifier failed: {type(error).__name__}: {error}")
        details["reasons"] = reasons
        return CheckResult(check="safety_gate", passed=not reasons, details=details)
