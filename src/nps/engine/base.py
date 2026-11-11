"""Engine interface. Nothing outside this package knows a concrete model."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from PIL import Image
from pydantic import BaseModel, ConfigDict

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


class GenerationResult:
    def __init__(self, image: Image.Image, manifest: Manifest) -> None:
        self.image = image
        self.manifest = manifest


class Engine(Protocol):
    def describe(self) -> EngineInfo: ...

    def capabilities(self) -> set[Capability]: ...

    def generate(self, request: GenerationRequest) -> GenerationResult: ...
