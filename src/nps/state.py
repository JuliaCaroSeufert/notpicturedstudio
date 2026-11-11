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
class ShootingState:
    shooting_id: str
    brief: dict[str, Any]
    brief_sha256: str
    product_sha256: str
    motifs: dict[str, MotifState] = field(default_factory=dict)


@dataclass
class CampaignState:
    campaign_id: str
    shootings: dict[str, ShootingState] = field(default_factory=dict)
    assets: dict[str, VariantState] = field(default_factory=dict)
    rejected_briefs: list[dict[str, Any]] = field(default_factory=list)
    notices: set[str] = field(default_factory=set)
    entries: int = 0
    head_hash: str | None = None

    def motif_of(self, asset_id: str) -> MotifState:
        variant = self.assets[asset_id]
        return self.shootings[variant.shooting_id].motifs[variant.motif_id]


NOTICE_TEST_ENGINE = "Bild stammt aus einer Test-Engine, nicht aus einem Produktionsmodell."
NOTICE_PLACEHOLDER_GATE = "Safety-Gate ist ein Platzhalter, kein Klassifikator."
NOTICE_LABEL_ONLY = "Kennzeichnung nur als sichtbares Label; C2PA und Wasserzeichen fehlen noch."


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
        if entry.event == "shooting_registered":
            state.shootings[payload["shooting_id"]] = ShootingState(
                shooting_id=payload["shooting_id"],
                brief=payload["brief"],
                brief_sha256=payload["brief_sha256"],
                product_sha256=payload["product_sha256"],
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
        if "manifest" in payload:
            variant.manifest = payload["manifest"]
        if "composed_sha256" in payload:
            variant.composed_sha256 = payload["composed_sha256"]
        if "review" in payload:
            variant.reviews.append(payload["review"])
        if payload.get("engine_production") is False:
            state.notices.add(NOTICE_TEST_ENGINE)
        if payload.get("gate_production") is False:
            state.notices.add(NOTICE_PLACEHOLDER_GATE)

        motif = state.motif_of(entry.asset_id)
        if entry.event == "asset_sealed":
            state.notices.add(NOTICE_LABEL_ONLY)
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
