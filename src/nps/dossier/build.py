"""Compliance dossier, built from the audit chain and nothing else."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from nps.audit.chain import AuditLog
from nps.state import read_campaign


def build_dossier(log: AuditLog, campaign_id: str) -> dict[str, Any]:
    state = read_campaign(log, campaign_id)
    shootings = []
    for shooting in state.shootings.values():
        motifs = []
        for motif in shooting.motifs.values():
            motifs.append(
                {
                    "motif_id": motif.motif_id,
                    "versions": [
                        {**asdict(version), "status": version.status.value}
                        for version in motif.versions
                    ],
                    "variants": [
                        {**asdict(variant), "state": variant.state.value}
                        for variant in motif.variants
                    ],
                }
            )
        shootings.append(
            {
                "shooting_id": shooting.shooting_id,
                "brief": shooting.brief,
                "brief_sha256": shooting.brief_sha256,
                "product_sha256": shooting.product_sha256,
                "motifs": motifs,
            }
        )
    return {
        "campaign_id": campaign_id,
        "chain": {
            "verified": True,
            "entries_total": len(log.entries()),
            "entries_campaign": state.entries,
            "head_hash": state.head_hash,
        },
        "notices": sorted(state.notices),
        "rejected_briefs": state.rejected_briefs,
        "shootings": shootings,
    }
