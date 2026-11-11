"""Deterministic CPU engine for tests and the first end-to-end run.

It draws an abstract image derived from prompt and seed. It never produces
people, which is why the development safety gate may let its output through.
"""

from __future__ import annotations

import hashlib
import platform

import numpy as np
import PIL
from PIL import Image

from nps.core.hashing import sha256_image, sha256_json
from nps.core.models import Manifest
from nps.engine.base import Capability, EngineInfo, GenerationRequest, GenerationResult

MOCK_ENGINE_NAME = "mock"


class MockEngine:
    VERSION = "1"

    def describe(self) -> EngineInfo:
        return EngineInfo(name=MOCK_ENGINE_NAME, version=self.VERSION, production=False)

    def capabilities(self) -> set[Capability]:
        return {Capability.TEXT2IMG}

    def generate(self, request: GenerationRequest) -> GenerationResult:
        digest = hashlib.sha256(f"{request.seed}:{request.prompt}".encode("utf-8")).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))

        # Integer arithmetic only, so the result is identical on every platform.
        top = rng.integers(60, 256, size=3, dtype=np.int64)
        bottom = rng.integers(60, 256, size=3, dtype=np.int64)
        rows = np.arange(request.height, dtype=np.int64)[:, None]
        span = max(request.height - 1, 1)
        column = (top * (span - rows) + bottom * rows) // span
        pixels = np.broadcast_to(column[:, None, :], (request.height, request.width, 3)).copy()

        for _ in range(6):
            w = int(rng.integers(request.width // 8, request.width // 3 + 1))
            h = int(rng.integers(request.height // 8, request.height // 3 + 1))
            x = int(rng.integers(0, request.width - w + 1))
            y = int(rng.integers(0, request.height - h + 1))
            pixels[y : y + h, x : x + w] = rng.integers(0, 256, size=3, dtype=np.int64)

        image = Image.fromarray(pixels.astype(np.uint8), mode="RGB")
        manifest = Manifest(
            engine=MOCK_ENGINE_NAME,
            engine_version=self.VERSION,
            weights_sha256=None,
            model_revision=None,
            prompt=request.prompt,
            seed=request.seed,
            width=request.width,
            height=request.height,
            request_sha256=sha256_json(request.model_dump()),
            output_sha256=sha256_image(image),
            libraries={"numpy": np.__version__, "pillow": PIL.__version__},
            runtime={"python": platform.python_version(), "device": "cpu"},
        )
        return GenerationResult(image, manifest)
