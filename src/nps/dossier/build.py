"""Compliance dossier, built from the audit chain and nothing else."""

from __future__ import annotations

from typing import Any

from nps.audit.chain import AuditLog


def build_dossier(log: AuditLog, campaign_id: str) -> dict[str, Any]:
    entries = [entry for entry in log.verify() if entry.campaign_id == campaign_id]
    assets: dict[str, dict[str, Any]] = {}
    rejected_briefs: list[dict[str, Any]] = []
    notices: set[str] = set()

    for entry in entries:
        if entry.asset_id is None:
            if entry.event == "brief_rejected":
                rejected_briefs.append({"timestamp": entry.timestamp, **entry.payload})
            continue
        asset = assets.setdefault(
            entry.asset_id,
            {"asset_id": entry.asset_id, "state": None, "checks": [], "events": []},
        )
        asset["events"].append(
            {"seq": entry.seq, "timestamp": entry.timestamp, "event": entry.event, "hash": entry.hash}
        )
        payload = entry.payload
        if "state" in payload:
            asset["state"] = payload["state"]
        if "check" in payload:
            asset["checks"].append(payload["check"])
        for key in ("brief", "manifest", "review", "final_sha256", "label", "provenance"):
            if key in payload:
                asset[key] = payload[key]
        if payload.get("engine_production") is False:
            notices.add("Bild stammt aus einer Test-Engine, nicht aus einem Produktionsmodell.")
        if payload.get("gate_production") is False:
            notices.add("Safety-Gate ist ein Platzhalter, kein Klassifikator.")
        if entry.event == "asset_sealed":
            notices.add("Kennzeichnung nur als sichtbares Label; C2PA und Wasserzeichen fehlen noch.")

    return {
        "campaign_id": campaign_id,
        "chain": {
            "verified": True,
            "entries_total": len(log.entries()),
            "entries_campaign": len(entries),
            "head_hash": entries[-1].hash if entries else None,
        },
        "notices": sorted(notices),
        "rejected_briefs": rejected_briefs,
        "assets": list(assets.values()),
    }
