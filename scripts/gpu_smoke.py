"""First real run of the FLUX.2 [klein] adapter on a GPU.

Generates a fixed still life twice with the same seed and checks that both
runs give the identical image. The prompt is fixed on purpose and contains no
people: this script bypasses the pipeline and therefore the safety gate.

    python scripts/gpu_smoke.py --out smoke
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from nps.engine.base import GenerationRequest
from nps.engine.flux2_klein import Flux2KleinConfig, Flux2KleinEngine, Flux2Variant

PROMPT = (
    "Product photo of colourful wooden building blocks on a light oak floor, "
    "soft daylight from a window, empty room, no people"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--variant", choices=[v.value for v in Flux2Variant], default="distilled")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--local-dir", help="load the model from this folder, without network")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    engine = Flux2KleinEngine(
        Flux2KleinConfig(variant=Flux2Variant(args.variant), device=args.device, local_dir=args.local_dir)
    )
    request = GenerationRequest(prompt=PROMPT, seed=1234, width=1024, height=1024)

    started = time.monotonic()
    first = engine.generate(request)
    load_and_first = time.monotonic() - started
    started = time.monotonic()
    second = engine.generate(request)
    warm = time.monotonic() - started

    first.image.save(out / "smoke.png")
    (out / "manifest.json").write_text(json.dumps(first.manifest.model_dump(), indent=2), encoding="utf-8")
    identical = first.manifest.output_sha256 == second.manifest.output_sha256
    print(f"Laden + erstes Bild: {load_and_first:.1f} s, zweites Bild: {warm:.1f} s")
    print(f"Gewichte: {first.manifest.weights_sha256}")
    print(f"Gleicher Seed, gleiches Bild: {'ja' if identical else 'NEIN'}")
    return 0 if identical else 1


if __name__ == "__main__":
    sys.exit(main())
