"""Pipeline: shooting brief -> variants -> internal review -> versions -> client decision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from nps.audit.chain import AuditLog
from nps.core.hashing import sha256_bytes, sha256_image, sha256_json
from nps.core.models import (
    AssetState,
    CheckResult,
    MotifSpec,
    ShootingBrief,
    VersionStatus,
)
from nps.engine.base import Engine, GenerationRequest
from nps.intake.brief import screen_brief
from nps.intake.upload import (
    RejectAllUploadGate,
    UploadDecision,
    UploadGate,
    UploadVerdict,
    check_image_via_file,
)
from nps.product.composite import composite_product, verify_product_pixels
from nps.provenance.seal import Sealer
from nps.safety.gate import SafetyGate
from nps.state import CampaignState, VersionState, read_campaign


class PipelineError(Exception):
    """The requested step is not allowed in the current state."""


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str | None
    state: AssetState
    checks: tuple[CheckResult, ...]
    motif_id: str | None = None
    variant: int | None = None
    path: Path | None = None


@dataclass(frozen=True)
class VersionRecord:
    motif_id: str
    number: int
    asset_id: str
    status: VersionStatus
    path: Path | None = None


def build_prompt(brief: ShootingBrief, motif: MotifSpec) -> str:
    colors = ", ".join(brief.brand.colors)
    parts = [brief.scene, motif.description or ""]
    parts += [f"child, {p.age_years} years old: {p.description}" for p in brief.persons]
    parts.append(f"brand colours: {colors}" if colors else "")
    return ". ".join(part for part in parts if part)


def variant_seed(base_seed: int, motif_id: str, index: int) -> int:
    """Every variant gets its own seed, derived so that reruns give the same one."""
    digest = hashlib.sha256(f"{base_seed}:{motif_id}:{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _require_name(name: str, role: str) -> None:
    if not name.strip():
        raise PipelineError(f"a name is required for '{role}'")


class Pipeline:
    def __init__(
        self,
        out_dir: Path,
        engine: Engine,
        gate: SafetyGate,
        log: AuditLog | None = None,
        sealer: Sealer | None = None,
        upload_gate: UploadGate | None = None,
    ):
        self._out = Path(out_dir)
        self._engine = engine
        self._gate = gate
        self._sealer = sealer or Sealer()
        self._upload_gate = upload_gate or RejectAllUploadGate()
        self.log = log or AuditLog(self._out / "audit.jsonl")

    # -- storage ---------------------------------------------------------

    def _asset_dir(self, asset_id: str) -> Path:
        return self._out / "assets" / asset_id

    def _product_path(self, product_sha256: str) -> Path:
        return self._out / "products" / f"{product_sha256}.png"

    def _load_product(self, product_sha256: str) -> Image.Image:
        product = Image.open(self._product_path(product_sha256))
        product.load()
        if sha256_image(product) != product_sha256:
            raise PipelineError("stored product image no longer matches its recorded hash")
        return product

    def state(self, campaign_id: str) -> CampaignState:
        return read_campaign(self.log, campaign_id)

    # -- uploads ---------------------------------------------------------

    def _upload_path(self, sha256: str, pending: bool) -> Path:
        return self._out / "uploads" / ("pending" if pending else "accepted") / sha256

    def _record_upload(
        self,
        campaign_id: str,
        *,
        sha256: str,
        filename: str,
        purpose: str,
        uploaded_by: str,
        verdict: UploadVerdict,
        data: bytes | None,
    ) -> None:
        # Rejected files are not kept. Files waiting for a decision are kept apart.
        if data is not None and verdict.decision is not UploadDecision.REJECTED:
            target = self._upload_path(sha256, verdict.decision is UploadDecision.NEEDS_REVIEW)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.log.append(
            campaign_id=campaign_id,
            event="upload_checked",
            payload={
                "sha256": sha256,
                "filename": filename,
                "purpose": purpose,
                "uploaded_by": uploaded_by,
                "gate": self._upload_gate.name,
                "decision": verdict.decision.value,
                "reasons": list(verdict.reasons),
                "details": verdict.details,
            },
        )

    def register_upload(
        self, campaign_id: str, path: Path, *, purpose: str, uploaded_by: str
    ) -> tuple[str, UploadVerdict]:
        """Check a reference or product file. Returns its hash and the verdict."""
        _require_name(uploaded_by, "uploaded_by")
        path = Path(path)
        data = path.read_bytes()
        sha256 = sha256_bytes(data)
        known = self.state(campaign_id).uploads.get(sha256)
        if known is not None:
            return sha256, UploadVerdict(UploadDecision(known.decision), tuple(known.reasons), known.details)
        verdict = self._upload_gate.check_file(path)
        self._record_upload(
            campaign_id,
            sha256=sha256,
            filename=path.name,
            purpose=purpose,
            uploaded_by=uploaded_by,
            verdict=verdict,
            data=data,
        )
        return sha256, verdict

    def review_upload(
        self, campaign_id: str, sha256: str, reviewer: str, *, accept: bool, note: str = ""
    ) -> None:
        """A human decides on an upload the gate could not decide."""
        _require_name(reviewer, "reviewer")
        upload = self.state(campaign_id).uploads.get(sha256)
        if upload is None or upload.decision != UploadDecision.NEEDS_REVIEW.value:
            raise PipelineError(f"upload {sha256[:12]} is not waiting for a decision")
        pending = self._upload_path(sha256, pending=True)
        if pending.exists():
            if accept:
                target = self._upload_path(sha256, pending=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                pending.replace(target)
            else:
                pending.unlink()
        self.log.append(
            campaign_id=campaign_id,
            event="upload_reviewed",
            payload={"sha256": sha256, "reviewer": reviewer, "accepted": accept, "note": note},
        )

    def _product_admitted(self, campaign_id: str, product: Image.Image, product_sha: str) -> CheckResult:
        """The product image must have passed the upload gate, like any other upload."""
        upload = self.state(campaign_id).uploads.get(product_sha)
        if upload is None:
            verdict = check_image_via_file(self._upload_gate, product)
            self._record_upload(
                campaign_id,
                sha256=product_sha,
                filename="product",
                purpose="product",
                uploaded_by="pipeline",
                verdict=verdict,
                data=None,
            )
            decision, reasons = verdict.decision.value, list(verdict.reasons)
        else:
            decision, reasons = upload.decision, upload.reasons
        return CheckResult(
            check="product_upload",
            passed=decision == UploadDecision.ACCEPTED.value,
            details={"decision": decision, "reasons": reasons, "sha256": product_sha},
        )

    # -- generation ------------------------------------------------------

    def generate_shooting(self, brief: ShootingBrief, product: Image.Image) -> list[AssetRecord]:
        """Register the shooting and generate the configured variants for every motif."""
        records: list[AssetRecord] = []
        for motif in brief.motifs:
            batch = self.generate_variants(brief, product, motif.motif_id)
            records += batch
            if batch[0].asset_id is None:
                break  # the brief itself was rejected
        return records

    def generate_variants(
        self, brief: ShootingBrief, product: Image.Image, motif_id: str, count: int | None = None
    ) -> list[AssetRecord]:
        """Generate further variants of one motif. Each stops at human review."""
        campaign = brief.campaign_id
        brief_data = brief.model_dump(mode="json")
        brief_sha, product_sha = sha256_json(brief_data), sha256_image(product)
        motif = brief.motif(motif_id)

        shooting = self.state(campaign).shootings.get(brief.shooting_id)
        if shooting is None:
            screening = screen_brief(brief)
            if not screening.passed:
                self.log.append(
                    campaign_id=campaign,
                    event="brief_rejected",
                    payload={
                        "shooting_id": brief.shooting_id,
                        "brief": brief_data,
                        "check": screening.model_dump(),
                    },
                )
                return [AssetRecord(None, AssetState.REJECTED, (screening,))]
            admitted = self._product_admitted(campaign, product, product_sha)
            if not admitted.passed:
                # Nothing is registered or generated; the upload record says why.
                return [AssetRecord(None, AssetState.REJECTED, (admitted,))]
            path = self._product_path(product_sha)
            path.parent.mkdir(parents=True, exist_ok=True)
            product.save(path)
            self.log.append(
                campaign_id=campaign,
                event="shooting_registered",
                payload={
                    "shooting_id": brief.shooting_id,
                    "brief": brief_data,
                    "brief_sha256": brief_sha,
                    "product_sha256": product_sha,
                    "check": screening.model_dump(),
                },
            )
            start = 0
        else:
            # A registered shooting is frozen. Changes need a new shooting id, so
            # every image can be traced to exactly one brief.
            if shooting.brief_sha256 != brief_sha or shooting.product_sha256 != product_sha:
                raise PipelineError(
                    f"shooting '{brief.shooting_id}' is already registered with a different "
                    "brief or product; use a new shooting id"
                )
            start = len(shooting.motifs[motif_id].variants)

        total = count if count is not None else brief.variants_per_motif
        return [
            self._generate_one(brief, product, product_sha, motif, index)
            for index in range(start, start + total)
        ]

    def _generate_one(
        self,
        brief: ShootingBrief,
        product: Image.Image,
        product_sha: str,
        motif: MotifSpec,
        index: int,
    ) -> AssetRecord:
        seed = variant_seed(brief.base_seed, motif.motif_id, index)
        asset_id = sha256_json(
            {
                "campaign": brief.campaign_id,
                "shooting": brief.shooting_id,
                "motif": motif.motif_id,
                "variant": index,
                "product": product_sha,
            }
        )[:16]

        def record(event: str, payload: dict[str, Any]) -> None:
            self.log.append(
                campaign_id=brief.campaign_id, asset_id=asset_id, event=event, payload=payload
            )

        def done(state: AssetState, checks: list[CheckResult], path: Path | None = None) -> AssetRecord:
            return AssetRecord(asset_id, state, tuple(checks), motif.motif_id, index, path)

        record(
            "asset_planned",
            {
                "state": AssetState.PLANNED.value,
                "shooting_id": brief.shooting_id,
                "motif_id": motif.motif_id,
                "variant": index,
                "seed": seed,
            },
        )

        info = self._engine.describe()
        result = self._engine.generate(
            GenerationRequest(
                prompt=build_prompt(brief, motif), seed=seed, width=brief.width, height=brief.height
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

        checks: list[CheckResult] = []
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
            return done(AssetState.BLOCKED, checks)
        record(
            "safety_passed",
            {"check": safety.model_dump(), "gate_production": self._gate.production},
        )

        composed = composite_product(result.image, product, motif.placement)
        fidelity = verify_product_pixels(composed, product, motif.placement)
        checks.append(fidelity)
        if not fidelity.passed:
            record("asset_blocked", {"state": AssetState.BLOCKED.value, "check": fidelity.model_dump()})
            return done(AssetState.BLOCKED, checks)

        asset_dir = self._asset_dir(asset_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        composed.save(asset_dir / "composed.png")
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
        return done(AssetState.IN_REVIEW, checks, asset_dir / "composed.png")

    # -- internal review -------------------------------------------------

    def reject_variant(self, campaign_id: str, asset_id: str, reviewer: str, note: str = "") -> AssetRecord:
        _require_name(reviewer, "reviewer")
        variant = self._variant_in_review(self.state(campaign_id), asset_id)
        self.log.append(
            campaign_id=campaign_id,
            asset_id=asset_id,
            event="asset_rejected",
            payload={
                "state": AssetState.REJECTED.value,
                "review": {"reviewer": reviewer, "approved": False, "note": note},
            },
        )
        return AssetRecord(asset_id, AssetState.REJECTED, (), variant.motif_id, variant.index)

    def approve_variant(
        self, campaign_id: str, asset_id: str, reviewer: str, note: str = ""
    ) -> VersionRecord | AssetRecord:
        """Approve a variant internally. It is sealed and becomes the motif's next version.

        Returns an AssetRecord in state BLOCKED if a check fails during sealing.
        """
        _require_name(reviewer, "reviewer")
        state = self.state(campaign_id)
        variant = self._variant_in_review(state, asset_id)
        shooting = state.shootings[variant.shooting_id]
        motif_state = shooting.motifs[variant.motif_id]

        latest = motif_state.latest_version
        if latest is not None and latest.status is not VersionStatus.CHANGES_REQUESTED:
            raise PipelineError(
                f"motif '{variant.motif_id}' already has version V{latest.number} in state "
                f"'{latest.status.value}'; a new version needs a change request from the client"
            )

        def record(event: str, payload: dict[str, Any]) -> None:
            self.log.append(campaign_id=campaign_id, asset_id=asset_id, event=event, payload=payload)

        def blocked(check: CheckResult) -> AssetRecord:
            record("asset_blocked", {"state": AssetState.BLOCKED.value, "check": check.model_dump()})
            return AssetRecord(asset_id, AssetState.BLOCKED, (check,), variant.motif_id, variant.index)

        brief = ShootingBrief.model_validate(shooting.brief)
        placement = brief.motif(variant.motif_id).placement
        product = self._load_product(shooting.product_sha256)
        asset_dir = self._asset_dir(asset_id)
        composed = Image.open(asset_dir / "composed.png")
        composed.load()

        # The file on disk must still be the one that passed the checks.
        if sha256_image(composed) != variant.composed_sha256:
            return blocked(
                CheckResult(
                    check="stored_image_integrity",
                    passed=False,
                    details={"expected": variant.composed_sha256},
                )
            )

        record(
            "asset_approved",
            {
                "state": AssetState.APPROVED.value,
                "review": {"reviewer": reviewer, "approved": True, "note": note},
            },
        )

        manifest = variant.manifest or {}
        sealed = self._sealer.seal(
            composed,
            product,
            placement,
            asset_id=asset_id,
            title=f"{campaign_id}-{variant.motif_id}-{asset_id}.png",
            asset_info={
                "campaign_id": campaign_id,
                "engine": manifest.get("engine"),
                "model_revision": manifest.get("model_revision"),
                "ai_generated": True,
            },
        )
        if not sealed.passed:
            return blocked(sealed.checks[-1])

        number = len(motif_state.versions) + 1
        final_path = asset_dir / "final.png"
        final_path.write_bytes(sealed.png)
        record(
            "asset_sealed",
            {
                "state": AssetState.SEALED.value,
                "checks": [check.model_dump() for check in sealed.checks],
                "final_sha256": sha256_bytes(sealed.png),
                "final_pixels_sha256": sealed.pixels_sha256,
                "label": sealed.label,
                "provenance": sealed.provenance,
                "version": {
                    "number": number,
                    "parent": latest.number if latest else None,
                    "approved_by": reviewer,
                    "note": note,
                },
            },
        )
        return VersionRecord(variant.motif_id, number, asset_id, VersionStatus.SEALED, final_path)

    # -- client ----------------------------------------------------------

    def release_version(
        self, campaign_id: str, shooting_id: str, motif_id: str, number: int, released_by: str
    ) -> VersionRecord:
        """Mark a sealed version as shown to the client."""
        _require_name(released_by, "released_by")
        version = self._version(campaign_id, shooting_id, motif_id, number, VersionStatus.SEALED)
        self.log.append(
            campaign_id=campaign_id,
            asset_id=version.asset_id,
            event="version_released",
            payload={"version": number, "released_by": released_by},
        )
        return VersionRecord(motif_id, number, version.asset_id, VersionStatus.RELEASED)

    def customer_decision(
        self,
        campaign_id: str,
        shooting_id: str,
        motif_id: str,
        number: int,
        *,
        approved: bool,
        recorded_by: str,
        comment: str = "",
    ) -> VersionRecord:
        """Record the client's approval or change request for a released version."""
        _require_name(recorded_by, "recorded_by")
        if not approved and not comment.strip():
            raise PipelineError("a change request needs a comment")
        version = self._version(campaign_id, shooting_id, motif_id, number, VersionStatus.RELEASED)
        self.log.append(
            campaign_id=campaign_id,
            asset_id=version.asset_id,
            event="customer_decision",
            payload={
                "version": number,
                "approved": approved,
                "comment": comment,
                "recorded_by": recorded_by,
            },
        )
        status = VersionStatus.CUSTOMER_APPROVED if approved else VersionStatus.CHANGES_REQUESTED
        return VersionRecord(motif_id, number, version.asset_id, status)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _variant_in_review(state: CampaignState, asset_id: str):
        variant = state.assets.get(asset_id)
        if variant is None:
            raise PipelineError(f"unknown asset {asset_id}")
        if variant.state is not AssetState.IN_REVIEW:
            raise PipelineError(
                f"asset {asset_id} is in state '{variant.state.value}', not waiting for review"
            )
        return variant

    def _version(
        self, campaign_id: str, shooting_id: str, motif_id: str, number: int, required: VersionStatus
    ) -> VersionState:
        try:
            motif = self.state(campaign_id).shootings[shooting_id].motifs[motif_id]
            version = motif.versions[number - 1] if number >= 1 else None
        except (KeyError, IndexError):
            version = None
        if version is None:
            raise PipelineError(f"unknown version V{number} of motif '{motif_id}'")
        if version.status is not required:
            raise PipelineError(
                f"version V{number} of motif '{motif_id}' is in state '{version.status.value}', "
                f"expected '{required.value}'"
            )
        return version
