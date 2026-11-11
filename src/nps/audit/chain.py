"""Append-only hash chain.

Step 0 stores the chain as a JSON-lines file. The interface is what the rest of
the system depends on; a Postgres backend with RFC 3161 timestamps replaces the
file later without touching callers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from nps.core.hashing import sha256_json

GENESIS_HASH = "0" * 64


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    timestamp: str
    campaign_id: str
    asset_id: str | None
    event: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str

    def body(self) -> dict[str, Any]:
        return self.model_dump(exclude={"hash"})


class ChainError(Exception):
    """The stored chain is not intact."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog:
    def __init__(self, path: Path, clock: Callable[[], datetime] = _utc_now) -> None:
        self._path = Path(path)
        self._clock = clock

    @property
    def path(self) -> Path:
        return self._path

    def entries(self) -> list[AuditEntry]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            return [AuditEntry.model_validate_json(line) for line in handle if line.strip()]

    def verify(self) -> list[AuditEntry]:
        """Return all entries, or raise ChainError at the first broken link."""
        entries = self.entries()
        prev = GENESIS_HASH
        for index, entry in enumerate(entries):
            if entry.seq != index:
                raise ChainError(f"entry {index}: unexpected sequence number {entry.seq}")
            if entry.prev_hash != prev:
                raise ChainError(f"entry {index}: previous hash does not match")
            if sha256_json(entry.body()) != entry.hash:
                raise ChainError(f"entry {index}: content does not match its hash")
            prev = entry.hash
        return entries

    def append(
        self,
        *,
        campaign_id: str,
        event: str,
        payload: dict[str, Any],
        asset_id: str | None = None,
    ) -> AuditEntry:
        # Verifying before every append means a tampered chain cannot be extended.
        entries = self.verify()
        body = {
            "seq": len(entries),
            "timestamp": self._clock().isoformat(),
            "campaign_id": campaign_id,
            "asset_id": asset_id,
            "event": event,
            # Round-trip through JSON so the hashed form equals the stored form.
            "payload": json.loads(json.dumps(payload)),
            "prev_hash": entries[-1].hash if entries else GENESIS_HASH,
        }
        entry = AuditEntry(**body, hash=sha256_json(body))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
        return entry
