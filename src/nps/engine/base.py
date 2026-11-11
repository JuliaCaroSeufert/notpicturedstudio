"""Engine interface. Nothing outside this package knows a concrete model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from PIL import Image
from pydantic import BaseModel, ConfigDict

from nps.core.hashing import sha256_bytes, sha256_image
from nps.core.models import Manifest


class Capability(str, Enum):
    TEXT2IMG = "text2img"
    MULTI_REFERENCE = "multi_reference"
    INPAINT = "inpaint"
    CONTROL_DEPTH = "control_depth"
    CONTROL_POSE = "control_pose"
    LORA = "lora"


class EngineInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    weights_sha256: str | None = None
    model_revision: str | None = None
    production: bool


class GenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str
    seed: int
    width: int
    height: int
    # Hashes of reference images and LoRA weights. The files themselves travel
    # in GenerationInputs; the hashes make them part of the reproducible request.
    reference_sha256: tuple[str, ...] = ()
    lora_sha256: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationInputs:
    references: tuple[Image.Image, ...] = ()
    lora_paths: tuple[Path, ...] = ()


def check_inputs(request: GenerationRequest, inputs: GenerationInputs | None) -> GenerationInputs:
    """Make sure the files handed over are exactly the ones the request names."""
    inputs = inputs or GenerationInputs()
    references = tuple(sha256_image(image) for image in inputs.references)
    loras = tuple(sha256_bytes(Path(path).read_bytes()) for path in inputs.lora_paths)
    if references != request.reference_sha256 or loras != request.lora_sha256:
        raise ValueError("reference images or LoRA files do not match the hashes in the request")
    return inputs


class GenerationResult:
    def __init__(self, image: Image.Image, manifest: Manifest) -> None:
        self.image = image
        self.manifest = manifest


class Engine(Protocol):
    def describe(self) -> EngineInfo: ...

    def capabilities(self) -> set[Capability]: ...

    def generate(
        self, request: GenerationRequest, inputs: GenerationInputs | None = None
    ) -> GenerationResult: ...
