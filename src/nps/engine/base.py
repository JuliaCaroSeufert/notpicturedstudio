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
    # Inpainting (Capability.INPAINT): the engine starts from the canvas and
    # repaints only where the mask is white. Both are given together or not at all.
    canvas_sha256: str | None = None
    mask_sha256: str | None = None


@dataclass(frozen=True)
class GenerationInputs:
    references: tuple[Image.Image, ...] = ()
    lora_paths: tuple[Path, ...] = ()
    canvas: Image.Image | None = None
    mask: Image.Image | None = None


def check_inputs(request: GenerationRequest, inputs: GenerationInputs | None) -> GenerationInputs:
    """Make sure the files handed over are exactly the ones the request names."""
    inputs = inputs or GenerationInputs()
    references = tuple(sha256_image(image) for image in inputs.references)
    loras = tuple(sha256_bytes(Path(path).read_bytes()) for path in inputs.lora_paths)
    if references != request.reference_sha256 or loras != request.lora_sha256:
        raise ValueError("reference images or LoRA files do not match the hashes in the request")
    canvas = sha256_image(inputs.canvas) if inputs.canvas is not None else None
    mask = sha256_image(inputs.mask) if inputs.mask is not None else None
    if canvas != request.canvas_sha256 or mask != request.mask_sha256:
        raise ValueError("canvas or mask do not match the hashes in the request")
    if (canvas is None) != (mask is None):
        raise ValueError("canvas and mask must be given together")
    if inputs.canvas is not None and (
        inputs.canvas.size != (request.width, request.height) or inputs.mask.size != inputs.canvas.size
    ):
        raise ValueError("canvas and mask must have the requested size")
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
