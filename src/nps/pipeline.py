"""Step-0 pipeline: brief -> generation -> checks -> review -> sealed file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from nps.audit.chain import AuditLog
from nps.core.hashing import sha256_bytes, sha256_image, sha256_json
from nps.core.models import AssetState, Brief, CheckResult
from nps.engine.base import Engine, GenerationRequest
from nps.intake.brief import screen_brief
from nps.product.composite import composite_product, product_box, verify_product_pixels
from nps.provenance.label import LABEL_TEXT, apply_visible_label
from nps.safety.gate import SafetyGate


class PipelineError(Exception):
    """The requested step is not allowed in the asset's current state."""


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str | None
    state: AssetState
    checks: tuple[CheckResult, ...]
    path: Path | None = None


def build_prompt(brief: Brief) -> str:
    colors = ", ".join(brief.brand.colors)
    parts = [
        brief.scene,
        f"{brief.child.age_group.value}: {brief.child.description}",
        f"brand colours: {colors}" if colors else "",
    ]
    return ". ".join(part for part in parts if part)


class Pipeline:
    def __init__(self, out_dir: Path, engine: Engine, gate: SafetyGate, log: AuditLog | None = None):
        self._out = Path(out_dir)
        self._engine = engine
        self._gate = gate
        self.log = log or AuditLog(self._out / "audit.jsonl")

    def _asset_dir(self, asset_id: str) -> Path:
        return self._out / "assets" / asset_id

    def _state(self, asset_id: str) -> AssetState | None:
        state = None
        for entry in self.log.verify():
            if entry.asset_id == asset_id and "state" in entry.payload:
                state = AssetState(entry.payload["state"])
        return state

    def generate(self, brief: Brief, product: Image.Image) -> AssetRecord:
        """Run everything up to human review. Never returns an approved asset."""
        campaign = brief.campaign_id
        brief_data = brief.model_dump(mode="json")
        product_sha = sha256_image(product)

        screening = screen_brief(brief)
        if not screening.passed:
            self.log.append(
                campaign_id=campaign,
                event="brief_rejected",
                payload={"brief": brief_data, "check": screening.model_dump()},
            )
            return AssetRecord(None, AssetState.REJECTED, (screening,))

        asset_id = sha256_json({"brief": brief_data, "product": product_sha})[:16]
        if self._state(asset_id) is not None:
            raise PipelineError(f"asset {asset_id} already exists; change the seed for a new one")

        def record(event: str, payload: dict) -> None:
            self.log.append(campaign_id=campaign, asset_id=asset_id, event=event, payload=payload)

        record(
            "asset_planned",
            {
                "state": AssetState.PLANNED.value,
                "brief": brief_data,
                "product_sha256": product_sha,
                "check": screening.model_dump(),
            },
        )

        info = self._engine.describe()
        result = self._engine.generate(
            GenerationRequest(
                prompt=build_prompt(brief), seed=brief.seed, width=brief.width, height=brief.height
            )
        )
        record(
            "asset_generated",
            {
                "state": AssetState.GENERATED.value,
                "manifest": result.manifest.model_dump(),
                "engine_production": info.production,
            },
        )

        checks = [screening]
        safety = self._gate.evaluate(result.image, result.manifest)
        checks.append(safety)
        if not safety.passed:
            # The blocked image is not written to disk; only its hash is kept.
            record(
                "asset_blocked",
                {
                    "state": AssetState.BLOCKED.value,
                    "check": safety.model_dump(),
                    "gate_production": self._gate.production,
                },
            )
            return AssetRecord(asset_id, AssetState.BLOCKED, tuple(checks))
        record(
            "safety_passed",
            {"check": safety.model_dump(), "gate_production": self._gate.production},
        )

        composed = composite_product(result.image, product, brief.placement)
        fidelity = verify_product_pixels(composed, product, brief.placement)
        checks.append(fidelity)
        if not fidelity.passed:
            record(
                "asset_blocked",
                {"state": AssetState.BLOCKED.value, "check": fidelity.model_dump()},
            )
            return AssetRecord(asset_id, AssetState.BLOCKED, tuple(checks))

        asset_dir = self._asset_dir(asset_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        composed.save(asset_dir / "composed.png")
        product.save(asset_dir / "product.png")
        (asset_dir / "manifest.json").write_text(
            json.dumps(result.manifest.model_dump(), indent=2), encoding="utf-8"
        )
        record(
            "asset_in_review",
            {
                "state": AssetState.IN_REVIEW.value,
                "check": fidelity.model_dump(),
                "composed_sha256": sha256_image(composed),
            },
        )
        return AssetRecord(asset_id, AssetState.IN_REVIEW, tuple(checks), asset_dir / "composed.png")

    def review(self, brief: Brief, asset_id: str, reviewer: str, approve: bool, note: str = "") -> AssetRecord:
        """Record a human decision. Approval seals the asset."""
        if not reviewer.strip():
            raise PipelineError("a reviewer name is required")
        if self._state(asset_id) is not AssetState.IN_REVIEW:
            raise PipelineError(f"asset {asset_id} is not waiting for review")

        campaign = brief.campaign_id
        review = {"reviewer": reviewer, "approved": approve, "note": note}

        def record(event: str, payload: dict) -> None:
            self.log.append(campaign_id=campaign, asset_id=asset_id, event=event, payload=payload)

        if not approve:
            record("asset_rejected", {"state": AssetState.REJECTED.value, "review": review})
            return AssetRecord(asset_id, AssetState.REJECTED, ())

        asset_dir = self._asset_dir(asset_id)
        composed = Image.open(asset_dir / "composed.png")
        composed.load()
        product = Image.open(asset_dir / "product.png")
        product.load()

        # The file on disk must still be the one that passed the checks.
        expected = next(
            entry.payload["composed_sha256"]
            for entry in self.log.verify()
            if entry.asset_id == asset_id and entry.event == "asset_in_review"
        )
        if sha256_image(composed) != expected:
            record(
                "asset_blocked",
                {
                    "state": AssetState.BLOCKED.value,
                    "check": CheckResult(
                        check="stored_image_integrity", passed=False, details={"expected": expected}
                    ).model_dump(),
                },
            )
            return AssetRecord(asset_id, AssetState.BLOCKED, ())

        record("asset_approved", {"state": AssetState.APPROVED.value, "review": review})

        labelled, label_box = apply_visible_label(composed, product_box(product, brief.placement))
        fidelity = verify_product_pixels(labelled, product, brief.placement)
        if not fidelity.passed:
            record("asset_blocked", {"state": AssetState.BLOCKED.value, "check": fidelity.model_dump()})
            return AssetRecord(asset_id, AssetState.BLOCKED, (fidelity,))

        final_path = asset_dir / "final.png"
        labelled.save(final_path)
        record(
            "asset_sealed",
            {
                "state": AssetState.SEALED.value,
                "check": fidelity.model_dump(),
                "final_sha256": sha256_bytes(final_path.read_bytes()),
                "label": {"text": LABEL_TEXT, "box": list(label_box)},
                "provenance": {"visible_label": True, "c2pa": False, "watermark": False},
            },
        )
        return AssetRecord(asset_id, AssetState.SEALED, (fidelity,), final_path)

