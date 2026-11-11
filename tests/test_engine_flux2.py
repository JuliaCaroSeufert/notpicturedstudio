import sys

import pytest
from PIL import Image

from nps.core.hashing import sha256_image
from nps.engine.flux2_klein import (
    Flux2KleinConfig,
    Flux2KleinEngine,
    Flux2Variant,
    LoadedModel,
    hash_model_dir,
)
from nps.engine.base import GenerationRequest
from nps.engine.registry import engine_by_name
from nps.pipeline import Pipeline
from nps.safety.gate import BlockAllGate, MockOnlyGate
from tests.fakes import open_upload_gate


class FakeBackend:
    """Stands in for the model: returns a colour derived from the seed."""

    def __init__(self, size=None):
        self.loads = 0
        self.calls = []
        self._size = size

    def load(self, config):
        self.loads += 1
        return LoadedModel(
            weights_sha256="w" * 64,
            libraries={"torch": "2.6.0", "diffusers": "0.42.1"},
            runtime={"device": config.device, "gpu": "Fake L40S"},
        )

    def run(self, **kwargs):
        self.calls.append(kwargs)
        size = self._size or (kwargs["width"], kwargs["height"])
        seed = kwargs["seed"]
        return Image.new("RGBA", size, (seed % 256, (seed >> 8) % 256, 7, 255))


def request(**overrides):
    data = {"prompt": "wooden blocks", "seed": 300, "width": 256, "height": 128}
    data.update(overrides)
    return GenerationRequest(**data)


def test_distilled_defaults_reach_the_model():
    backend = FakeBackend()
    Flux2KleinEngine(backend=backend).generate(request())
    assert backend.calls == [
        {
            "prompt": "wooden blocks",
            "seed": 300,
            "width": 256,
            "height": 128,
            "steps": 4,
            "guidance_scale": 1.0,
        }
    ]


def test_base_variant_uses_its_own_settings_and_repository():
    backend = FakeBackend()
    config = Flux2KleinConfig(variant=Flux2Variant.BASE)
    manifest = Flux2KleinEngine(config, backend).generate(request()).manifest
    assert (backend.calls[0]["steps"], backend.calls[0]["guidance_scale"]) == (50, 4.0)
    assert manifest.model_revision == (
        "black-forest-labs/FLUX.2-klein-base-4B@a3b4f4849157f664bdbc776fd7453c2783562f4d"
    )


def test_manifest_records_what_is_needed_to_reproduce():
    result = Flux2KleinEngine(backend=FakeBackend()).generate(request())
    manifest = result.manifest
    assert result.image.mode == "RGB"
    assert manifest.engine == "flux2-klein-4b"
    assert manifest.weights_sha256 == "w" * 64
    assert manifest.model_revision == (
        "black-forest-labs/FLUX.2-klein-4B@e7b7dc27f91deacad38e78976d1f2b499d76a294"
    )
    assert manifest.output_sha256 == sha256_image(result.image)
    assert manifest.libraries == {"torch": "2.6.0", "diffusers": "0.42.1"}
    assert manifest.runtime["gpu"] == "Fake L40S"
    assert (manifest.runtime["steps"], manifest.runtime["guidance_scale"]) == ("4", "1.0")
    assert manifest.runtime["variant"] == "distilled"


def test_settings_are_part_of_the_request_hash():
    fast = Flux2KleinEngine(backend=FakeBackend()).generate(request()).manifest
    slow = Flux2KleinEngine(Flux2KleinConfig(steps=8), FakeBackend()).generate(request()).manifest
    assert fast.request_sha256 != slow.request_sha256


def test_model_is_loaded_once_and_only_when_needed():
    backend = FakeBackend()
    engine = Flux2KleinEngine(backend=backend)
    assert engine.describe().weights_sha256 is None
    assert backend.loads == 0
    engine.generate(request())
    engine.generate(request(seed=301))
    assert backend.loads == 1
    assert engine.describe().weights_sha256 == "w" * 64
    assert engine.describe().production is True


def test_sizes_the_model_cannot_produce_are_rejected():
    backend = FakeBackend()
    with pytest.raises(ValueError, match="divisible by 16"):
        Flux2KleinEngine(backend=backend).generate(request(width=250))
    assert backend.loads == 0


def test_wrong_output_size_is_an_error():
    with pytest.raises(RuntimeError):
        Flux2KleinEngine(backend=FakeBackend(size=(64, 64))).generate(request())


def test_importing_the_adapter_needs_no_gpu_libraries():
    engine_by_name("flux2-klein-4b")
    assert "torch" not in sys.modules
    assert "diffusers" not in sys.modules


def test_environment_configures_the_adapter(monkeypatch):
    monkeypatch.setenv("NPS_FLUX2_VARIANT", "base")
    monkeypatch.setenv("NPS_DEVICE", "cuda:1")
    monkeypatch.setenv("NPS_FLUX2_LOCAL_DIR", "/models/flux")
    config = Flux2KleinConfig.from_env()
    assert (config.variant, config.device, config.local_dir) == (Flux2Variant.BASE, "cuda:1", "/models/flux")


def test_unknown_engine_name_is_an_error():
    with pytest.raises(ValueError):
        engine_by_name("flux-3")


def test_model_dir_hash_depends_on_content_and_names(tmp_path):
    def build(name, weights=b"abc", filename="model.safetensors"):
        root = tmp_path / name
        (root / "transformer").mkdir(parents=True)
        (root / "transformer" / filename).write_bytes(weights)
        (root / "model_index.json").write_text("{}")
        (root / "README.md").write_text(name)  # ignored
        return hash_model_dir(root)

    reference = build("a")
    assert build("b") == reference
    assert build("c", weights=b"abd") != reference
    assert build("d", filename="other.safetensors") != reference
    with pytest.raises(FileNotFoundError):
        hash_model_dir(tmp_path / "missing")


@pytest.mark.parametrize("gate", [BlockAllGate(), MockOnlyGate()])
def test_no_placeholder_gate_lets_real_model_output_through(tmp_path, brief, product, gate):
    pipe = Pipeline(
        tmp_path, Flux2KleinEngine(backend=FakeBackend()), gate, upload_gate=open_upload_gate()
    )
    records = pipe.generate_variants(brief, product, "m1", count=1)
    assert records[0].state.value == "blocked"
    assert not (tmp_path / "assets").exists()
