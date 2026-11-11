"""Current state of a campaign, derived from the audit chain alone.

Pipeline and dossier both read state through this module, so there is no second
store that could disagree with the chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nps.audit.chain import AuditLog
from nps.core.models import AssetState, VersionStatus


@dataclass
class VariantState:
    asset_id: str
    shooting_id: str
    motif_id: str
    index: int
    seed: int
    state: AssetState
    checks: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] | None = None
    composed_sha256: str | None = None
    reviews: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class VersionState:
    number: int
    asset_id: str
    parent: int | None
    status: VersionStatus
    approved_by: str
    note: str
    final_sha256: str
    final_pixels_sha256: str
    label: dict[str, Any]
    provenance: dict[str, Any]
    released_by: str | None = None
    customer: dict[str, Any] | None = None


@dataclass
class MotifState:
    motif_id: str
    variants: list[VariantState] = field(default_factory=list)
    versions: list[VersionState] = field(default_factory=list)

    @property
    def latest_version(self) -> VersionState | None:
        return self.versions[-1] if self.versions else None


@dataclass
class UploadState:
    sha256: str
    filename: str
    purpose: str
    decision: str  # accepted, needs_review or rejected; final after a review
    reasons: list[str]
    details: dict[str, Any]
    gate: str
    uploaded_by: str
    review: dict[str, Any] | None = None

    @property
    def usable(self) -> bool:
        return self.decision == "accepted"


@dataclass
class ShootingState:
    shooting_id: str
    brief: dict[str, Any]
    brief_sha256: str
    product_sha256: str
    identities: list[dict[str, Any]] = field(default_factory=list)
    motifs: dict[str, MotifState] = field(default_factory=dict)


@dataclass
class CampaignState:
    campaign_id: str
    shootings: dict[str, ShootingState] = field(default_factory=dict)
    assets: dict[str, VariantState] = field(default_factory=dict)
    rejected_briefs: list[dict[str, Any]] = field(default_factory=list)
    uploads: dict[str, UploadState] = field(default_factory=dict)
    notices: set[str] = field(default_factory=set)
    entries: int = 0
    head_hash: str | None = None

    def motif_of(self, asset_id: str) -> MotifState:
        variant = self.assets[asset_id]
        return self.shootings[variant.shooting_id].motifs[variant.motif_id]


NOTICE_TEST_ENGINE = "Bild stammt aus einer Test-Engine, nicht aus einem Produktionsmodell."
NOTICE_PLACEHOLDER_GATE = "Safety-Gate ist ein Platzhalter, kein Klassifikator."
NOTICE_PROVISIONAL_GATE = (
    "Safety-Gate ist ein Provisorium aus allgemeinen Nacktheits-Klassifikatoren; "
    "ein Kinderschutz-Klassifikator (Thorn) ist noch nicht angebunden."
)
NOTICE_NO_C2PA = "Mindestens ein Bild ohne C2PA-Signatur."
NOTICE_UNTRUSTED_C2PA = "C2PA-Signatur mit nicht anerkanntem Zertifikat (Testzertifikat)."
NOTICE_NO_WATERMARK = "Mindestens ein Bild ohne unsichtbares Wasserzeichen."


def read_campaign(log: AuditLog, campaign_id: str) -> CampaignState:
    """Replay the verified chain. Raises ChainError if the chain is broken."""
    state = CampaignState(campaign_id)
    for entry in log.verify():
        if entry.campaign_id != campaign_id:
            continue
        state.entries += 1
        state.head_hash = entry.hash
        payload = entry.payload

        if entry.event == "brief_rejected":
            state.rejected_briefs.append({"timestamp": entry.timestamp, **payload})
            continue
        if entry.event == "upload_checked":
            state.uploads[payload["sha256"]] = UploadState(
                sha256=payload["sha256"],
                filename=payload["filename"],
                purpose=payload["purpose"],
                decision=payload["decision"],
                reasons=payload["reasons"],
                details=payload["details"],
                gate=payload["gate"],
                uploaded_by=payload["uploaded_by"],
            )
            continue
        if entry.event == "upload_reviewed":
            upload = state.uploads[payload["sha256"]]
            upload.decision = "accepted" if payload["accepted"] else "rejected"
            upload.review = {
                "reviewer": payload["reviewer"],
                "accepted": payload["accepted"],
                "note": payload["note"],
                "timestamp": entry.timestamp,
            }
            continue
        if entry.event == "shooting_registered":
            state.shootings[payload["shooting_id"]] = ShootingState(
                shooting_id=payload["shooting_id"],
                brief=payload["brief"],
                brief_sha256=payload["brief_sha256"],
                product_sha256=payload["product_sha256"],
                identities=payload.get("identities", []),
                motifs={m["motif_id"]: MotifState(m["motif_id"]) for m in payload["brief"]["motifs"]},
            )
            continue
        if entry.asset_id is None:
            continue

        if entry.event == "asset_planned":
            variant = VariantState(
                asset_id=entry.asset_id,
                shooting_id=payload["shooting_id"],
                motif_id=payload["motif_id"],
                index=payload["variant"],
                seed=payload["seed"],
                state=AssetState.PLANNED,
            )
            state.assets[entry.asset_id] = variant
            state.shootings[variant.shooting_id].motifs[variant.motif_id].variants.append(variant)

        variant = state.assets[entry.asset_id]
        variant.events.append(
            {"seq": entry.seq, "timestamp": entry.timestamp, "event": entry.event, "hash": entry.hash}
        )
        if "state" in payload:
            variant.state = AssetState(payload["state"])
        if "check" in payload:
            variant.checks.append(payload["check"])
        variant.checks.extend(payload.get("checks", []))
        if "manifest" in payload:
            variant.manifest = payload["manifest"]
        if "composed_sha256" in payload:
            variant.composed_sha256 = payload["composed_sha256"]
        if "review" in payload:
            variant.reviews.append(payload["review"])
        if payload.get("engine_production") is False:
            state.notices.add(NOTICE_TEST_ENGINE)
        if payload.get("gate_production") is False:
            provisional = payload["check"]["details"].get("gate") == "provisional"
            state.notices.add(NOTICE_PROVISIONAL_GATE if provisional else NOTICE_PLACEHOLDER_GATE)

        motif = state.motif_of(entry.asset_id)
        if entry.event == "asset_sealed":
            provenance = payload["provenance"]
            if not provenance["c2pa"]:
                state.notices.add(NOTICE_NO_C2PA)
            elif provenance["c2pa"]["state"] != "Trusted":
                state.notices.add(NOTICE_UNTRUSTED_C2PA)
            if not provenance["watermark"]:
                state.notices.add(NOTICE_NO_WATERMARK)
            version = payload["version"]
            motif.versions.append(
                VersionState(
                    number=version["number"],
                    asset_id=entry.asset_id,
                    parent=version["parent"],
                    status=VersionStatus.SEALED,
                    approved_by=version["approved_by"],
                    note=version["note"],
                    final_sha256=payload["final_sha256"],
                    final_pixels_sha256=payload["final_pixels_sha256"],
                    label=payload["label"],
                    provenance=payload["provenance"],
                )
            )
        elif entry.event == "version_released":
            current = motif.versions[payload["version"] - 1]
            current.status = VersionStatus.RELEASED
            current.released_by = payload["released_by"]
        elif entry.event == "customer_decision":
            current = motif.versions[payload["version"] - 1]
            current.status = (
                VersionStatus.CUSTOMER_APPROVED
                if payload["approved"]
                else VersionStatus.CHANGES_REQUESTED
            )
            current.customer = {
                "approved": payload["approved"],
                "comment": payload["comment"],
                "recorded_by": payload["recorded_by"],
                "timestamp": entry.timestamp,
            }
    return state
