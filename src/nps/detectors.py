"""Pinned detection models used by the upload gate and the provisional safety gate.

Every file is pinned to a repository revision and a checksum. A file that is
missing or differs is an error, so a gate can never run on unknown weights.
Licences: docs/LIZENZPRUEFUNG_SCHRITT3.md.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class ModelError(Exception):
    """A pinned model file is missing or does not match its checksum."""


@dataclass(frozen=True)
class PinnedModel:
    key: str
    repo: str
    revision: str
    licence: str
    files: dict[str, str]  # file name -> sha256

    def url(self, filename: str) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{filename}"

    def verify(self, models_dir: Path) -> Path:
        folder = Path(models_dir) / self.key
        for filename, expected in self.files.items():
            path = folder / filename
            if not path.is_file():
                raise ModelError(f"model file missing: {path} (run scripts/fetch_models.py)")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ModelError(f"model file does not match its pinned checksum: {path}")
        return folder

    def identity(self) -> dict[str, str]:
        return {"repo": self.repo, "revision": self.revision, "licence": self.licence}


FREEPIK = PinnedModel(
    key="freepik",
    repo="Freepik/nsfw_image_detector",
    revision="15b85477e4fd2000db76ae9aae0f89a72f95e2e3",
    licence="MIT",
    files={
        "config.json": "39f53e86cc4868e0e11396b523c906f376621f54c1025ffc9ee2ee840542a41b",
        "model.safetensors": "024a9d4818fae2656403bf626c9f8c9e7789c2da274749fbebb1060d8fdaa7ab",
    },
)
MARQO = PinnedModel(
    key="marqo",
    repo="Marqo/nsfw-image-detection-384",
    revision="0c26ec22111b83f106d72a55f611ec35962bcb65",
    licence="Apache-2.0",
    files={
        "config.json": "ae848d1dca0aeccd38f2ebb4b1bb47219cdc7f34e3ddc50c8d6430abe74d79b4",
        "model.safetensors": "6bf2e0f64a1d20169736c2836e3a787b12379fdc08ba87f7d94a7a3d58eeefce",
    },
)
RTDETR = PinnedModel(
    key="rtdetr",
    repo="PekingU/rtdetr_v2_r50vd",
    revision="282494075698cab9faa1096ae26856890030c817",
    licence="Apache-2.0",
    files={
        "config.json": "d754c04c9a4c6d015d8393fa2dae4c63f4a9f0ba173c3d1a66e55cff59d8f060",
        "preprocessor_config.json": "cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1",
        "model.safetensors": "3331d977dbc0c7a6cdae9ec0b0b6ad156eb6720d65b7cf0fa710dcc541d88d71",
    },
)
YUNET = PinnedModel(
    key="yunet",
    repo="opencv/face_detection_yunet",
    revision="3cc26e7f1014a5ee5d74a42acee58bafc9d0a310",
    licence="MIT",
    files={
        "face_detection_yunet_2023mar.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
)
ALL_MODELS = (FREEPIK, MARQO, RTDETR, YUNET)


def models_dir() -> Path:
    return Path(os.environ.get("NPS_MODELS_DIR", "models"))
