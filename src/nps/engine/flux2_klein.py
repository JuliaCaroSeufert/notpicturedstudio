"""FLUX.2 [klein] 4B adapter.

The heavy libraries (torch, diffusers) are imported only when the real backend
loads the model, so the rest of the system and all tests run without them. The
adapter itself only shapes requests and manifests; everything that touches the
model sits behind `Backend`.
"""

from __future__ import annotations

import hashlib
import os
import platform
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from nps.core.hashing import sha256_image, sha256_json
from nps.core.models import Manifest
from nps.engine.base import (
    Capability,
    EngineInfo,
    GenerationInputs,
    GenerationRequest,
    GenerationResult,
)

ENGINE_NAME = "flux2-klein-4b"

# Only the component folders are needed; the repositories also carry a
# single-file copy of the same weights.
_MODEL_FILES = [
    "model_index.json",
    "scheduler/*",
    "text_encoder/*",
    "tokenizer/*",
    "transformer/*",
    "vae/*",
]


class Flux2Variant(str, Enum):
    DISTILLED = "distilled"  # fast, 4 steps
    BASE = "base"  # undistilled, for LoRA training and custom pipelines


@dataclass(frozen=True)
class _VariantDefaults:
    repo_id: str
    revision: str
    steps: int
    guidance_scale: float


# Revisions pinned to the state whose licence was read on 2026-11-11
# (docs/LIZENZPRUEFUNG.md). Changing a revision means reading the licence again.
_DEFAULTS = {
    Flux2Variant.DISTILLED: _VariantDefaults(
        "black-forest-labs/FLUX.2-klein-4B", "e7b7dc27f91deacad38e78976d1f2b499d76a294", 4, 1.0
    ),
    Flux2Variant.BASE: _VariantDefaults(
        "black-forest-labs/FLUX.2-klein-base-4B", "a3b4f4849157f664bdbc776fd7453c2783562f4d", 50, 4.0
    ),
}


@dataclass(frozen=True)
class Flux2KleinConfig:
    variant: Flux2Variant = Flux2Variant.DISTILLED
    device: str = "cuda"
    # Set to a directory to load from disk without any network access.
    local_dir: str | None = None
    steps: int | None = None
    guidance_scale: float | None = None

    @property
    def repo_id(self) -> str:
        return _DEFAULTS[self.variant].repo_id

    @property
    def revision(self) -> str:
        return _DEFAULTS[self.variant].revision

    @property
    def effective_steps(self) -> int:
        return self.steps if self.steps is not None else _DEFAULTS[self.variant].steps

    @property
    def effective_guidance(self) -> float:
        if self.guidance_scale is not None:
            return self.guidance_scale
        return _DEFAULTS[self.variant].guidance_scale

    @classmethod
    def from_env(cls) -> "Flux2KleinConfig":
        return cls(
            variant=Flux2Variant(os.environ.get("NPS_FLUX2_VARIANT", Flux2Variant.DISTILLED.value)),
            device=os.environ.get("NPS_DEVICE", "cuda"),
            local_dir=os.environ.get("NPS_FLUX2_LOCAL_DIR") or None,
        )


@dataclass(frozen=True)
class LoadedModel:
    weights_sha256: str
    libraries: dict[str, str]
    runtime: dict[str, str]


class Backend(Protocol):
    def load(self, config: Flux2KleinConfig) -> LoadedModel: ...

    def run(
        self, *, prompt: str, seed: int, width: int, height: int, steps: int, guidance_scale: float
    ) -> Image.Image: ...


def hash_model_dir(root: Path) -> str:
    """One hash over all weight and config files, independent of file order."""
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix in {".safetensors", ".json"}
    )
    if not files:
        raise FileNotFoundError(f"no model files found under {root}")
    for path in files:
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                file_digest.update(chunk)
        digest.update(f"{path.relative_to(root).as_posix()}\0{file_digest.hexdigest()}\n".encode())
    return digest.hexdigest()


class DiffusersBackend:
    """Runs the model with diffusers. Needs the `gpu` extra and a GPU."""

    def __init__(self) -> None:
        self._pipe: Any = None
        self._device = "cuda"

    def load(self, config: Flux2KleinConfig) -> LoadedModel:
        import diffusers
        import torch
        import transformers
        from diffusers import Flux2KleinPipeline

        if config.local_dir:
            model_dir = Path(config.local_dir)
        else:
            from huggingface_hub import snapshot_download

            model_dir = Path(
                snapshot_download(
                    config.repo_id, revision=config.revision, allow_patterns=_MODEL_FILES
                )
            )

        self._device = config.device
        self._pipe = Flux2KleinPipeline.from_pretrained(
            model_dir, torch_dtype=torch.bfloat16, local_files_only=True
        ).to(config.device)

        runtime = {
            "python": platform.python_version(),
            "device": config.device,
            "dtype": "bfloat16",
            "container_digest": os.environ.get("NPS_CONTAINER_DIGEST", "unknown"),
        }
        if config.device.startswith("cuda"):
            runtime["gpu"] = torch.cuda.get_device_name(torch.device(config.device))
            runtime["cuda"] = str(torch.version.cuda)
            runtime["cudnn"] = str(torch.backends.cudnn.version())
        return LoadedModel(
            weights_sha256=hash_model_dir(model_dir),
            libraries={
                "torch": torch.__version__,
                "diffusers": diffusers.__version__,
                "transformers": transformers.__version__,
            },
            runtime=runtime,
        )

    def run(
        self, *, prompt: str, seed: int, width: int, height: int, steps: int, guidance_scale: float
    ) -> Image.Image:
        import torch

        generator = torch.Generator(device=self._device).manual_seed(seed)
        return self._pipe(
            prompt=prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=generator,
        ).images[0]


class Flux2KleinEngine:
    VERSION = "1"

    def __init__(self, config: Flux2KleinConfig | None = None, backend: Backend | None = None):
        self._config = config or Flux2KleinConfig()
        self._backend = backend or DiffusersBackend()
        self._loaded: LoadedModel | None = None

    def _model(self) -> LoadedModel:
        if self._loaded is None:
            self._loaded = self._backend.load(self._config)
        return self._loaded

    def describe(self) -> EngineInfo:
        return EngineInfo(
            name=ENGINE_NAME,
            version=self.VERSION,
            weights_sha256=self._loaded.weights_sha256 if self._loaded else None,
            model_revision=self._config.revision,
            production=True,
        )

    def capabilities(self) -> set[Capability]:
        # The model also supports multi-reference editing, inpainting and LoRA;
        # they are listed here once the adapter implements and tests them.
        return {Capability.TEXT2IMG}

    def generate(
        self, request: GenerationRequest, inputs: GenerationInputs | None = None
    ) -> GenerationResult:
        if request.reference_sha256 or request.lora_sha256:
            raise NotImplementedError(
                "reference images and LoRA are not implemented in the FLUX.2 [klein] adapter yet"
            )
        if request.width % 16 or request.height % 16:
            raise ValueError("FLUX.2 [klein] needs width and height divisible by 16")
        model = self._model()
        settings = {
            "variant": self._config.variant.value,
            "steps": self._config.effective_steps,
            "guidance_scale": self._config.effective_guidance,
        }
        image = self._backend.run(
            prompt=request.prompt,
            seed=request.seed,
            width=request.width,
            height=request.height,
            steps=settings["steps"],
            guidance_scale=settings["guidance_scale"],
        ).convert("RGB")
        if image.size != (request.width, request.height):
            raise RuntimeError(f"model returned {image.size}, expected {request.width}x{request.height}")
        manifest = Manifest(
            engine=ENGINE_NAME,
            engine_version=self.VERSION,
            weights_sha256=model.weights_sha256,
            model_revision=f"{self._config.repo_id}@{self._config.revision}",
            prompt=request.prompt,
            seed=request.seed,
            width=request.width,
            height=request.height,
            request_sha256=sha256_json({"request": request.model_dump(), "settings": settings}),
            output_sha256=sha256_image(image),
            libraries=model.libraries,
            runtime={**model.runtime, **{key: str(value) for key, value in settings.items()}},
        )
        return GenerationResult(image, manifest)
