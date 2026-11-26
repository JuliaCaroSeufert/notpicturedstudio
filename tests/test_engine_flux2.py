import sys

import pytest
from PIL import Image

from nps.core.hashing import sha256_image
from nps.engine.flux2_klein import (
    Flux2KleinConfig,
    Flux2KleinEngine,
    Flux2Variant,
    hash_model_dir,
)
from nps.core.models import CheckResult
from nps.engine.base import Capability, GenerationInputs, GenerationRequest
from nps.product.composite import verify_product_pixels
from tests.conftest import make_brief
from nps.engine.registry import engine_by_name
from nps.pipeline import Pipeline
from nps.safety.gate import BlockAllGate, MockOnlyGate
from tests.engine_fakes import FakeBackend
from tests.fakes import open_upload_gate


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


def test_references_and_lora_are_refused_until_implemented():
    engine = Flux2KleinEngine(backend=FakeBackend())
    with pytest.raises(NotImplementedError):
        engine.generate(request(lora_sha256=("abc",)))
    with pytest.raises(NotImplementedError):
        engine.generate(request(reference_sha256=("abc",)))


# -- inpainting (scene around the product) ----------------------------------------


def inpaint_inputs(width=256, height=128):
    canvas = Image.new("RGB", (width, height), (128, 128, 128))
    mask = Image.new("L", (width, height), 255)
    return canvas, mask


def inpaint_request(canvas, mask, **overrides):
    return request(canvas_sha256=sha256_image(canvas), mask_sha256=sha256_image(mask), **overrides)


def test_adapter_offers_inpainting():
    assert Capability.INPAINT in Flux2KleinEngine(backend=FakeBackend()).capabilities()


def test_canvas_and_mask_reach_the_model_and_the_manifest():
    canvas, mask = inpaint_inputs()
    backend = FakeBackend()
    result = Flux2KleinEngine(backend=backend).generate(
        inpaint_request(canvas, mask), GenerationInputs(canvas=canvas, mask=mask)
    )
    assert backend.calls[0]["canvas"] is canvas and backend.calls[0]["mask"] is mask
    assert (result.manifest.runtime["mode"], result.manifest.runtime["strength"]) == ("inpaint", "1.0")
    plain = Flux2KleinEngine(backend=FakeBackend()).generate(request()).manifest
    assert "mode" not in plain.runtime
    assert plain.request_sha256 != result.manifest.request_sha256


def test_canvas_must_match_the_request():
    canvas, mask = inpaint_inputs()
    other = Image.new("RGB", canvas.size, (1, 2, 3))
    engine = Flux2KleinEngine(backend=FakeBackend())
    with pytest.raises(ValueError, match="canvas or mask"):
        engine.generate(inpaint_request(canvas, mask), GenerationInputs(canvas=other, mask=mask))
    with pytest.raises(ValueError, match="canvas or mask"):
        engine.generate(request(), GenerationInputs(canvas=canvas, mask=mask))


def test_canvas_needs_mask_and_the_requested_size():
    canvas, mask = inpaint_inputs()
    engine = Flux2KleinEngine(backend=FakeBackend())
    with pytest.raises(ValueError, match="together"):
        engine.generate(request(canvas_sha256=sha256_image(canvas)), GenerationInputs(canvas=canvas))
    small, small_mask = inpaint_inputs(128, 128)
    with pytest.raises(ValueError, match="requested size"):
        engine.generate(inpaint_request(small, small_mask), GenerationInputs(canvas=small, mask=small_mask))


class PassGate:
    """Lets everything through; only for checking the data flow."""

    name = "pass"
    production = False

    def evaluate(self, image, manifest):
        return CheckResult(check="safety", passed=True, details={})


def test_pipeline_paints_the_scene_around_the_product(tmp_path, product):
    brief = make_brief(product_description="a red and blue toy box")
    backend = FakeBackend()
    pipe = Pipeline(tmp_path, Flux2KleinEngine(backend=backend), PassGate(), upload_gate=open_upload_gate())
    record = pipe.generate_variants(brief, product, "m1", count=1)[0]
    assert record.state.value == "in_review"

    call = backend.calls[0]
    placement = brief.motif("m1").placement
    assert verify_product_pixels(call["canvas"], product, placement).passed
    assert call["mask"].getpixel((placement.x + 20, placement.y + 20)) == 0
    assert "a red and blue toy box" in call["prompt"]

    # The model's output is replaced by the real product pixels again.
    composed = Image.open(record.path)
    assert verify_product_pixels(composed, product, placement).passed
    manifest = pipe.state(brief.campaign_id).assets[record.asset_id].manifest
    assert manifest["runtime"]["mode"] == "inpaint"
