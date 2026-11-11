import json
from datetime import datetime, timezone

import pytest

from nps.audit.chain import GENESIS_HASH, AuditLog, ChainError


def fixed_clock():
    return datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def filled_log(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", clock=fixed_clock)
    for index in range(3):
        log.append(campaign_id="c", asset_id="a", event=f"e{index}", payload={"n": index})
    return log


def rewrite(log, mutate):
    lines = [json.loads(line) for line in log.path.read_text().splitlines()]
    mutate(lines)
    log.path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_entries_are_linked(tmp_path):
    entries = filled_log(tmp_path).verify()
    assert [entry.seq for entry in entries] == [0, 1, 2]
    assert entries[0].prev_hash == GENESIS_HASH
    assert entries[1].prev_hash == entries[0].hash
    assert entries[2].prev_hash == entries[1].hash


def test_same_content_gives_same_hashes(tmp_path):
    first = filled_log(tmp_path / "one").verify()
    second = filled_log(tmp_path / "two").verify()
    assert [entry.hash for entry in first] == [entry.hash for entry in second]


def test_changed_payload_is_detected(tmp_path):
    log = filled_log(tmp_path)
    rewrite(log, lambda lines: lines[1]["payload"].update(n=99))
    with pytest.raises(ChainError, match="entry 1"):
        log.verify()


def test_removed_entry_is_detected(tmp_path):
    log = filled_log(tmp_path)
    rewrite(log, lambda lines: lines.pop(1))
    with pytest.raises(ChainError):
        log.verify()


def test_reordered_entries_are_detected(tmp_path):
    log = filled_log(tmp_path)
    rewrite(log, lambda lines: lines.reverse())
    with pytest.raises(ChainError):
        log.verify()


def test_tampered_chain_cannot_be_extended(tmp_path):
    log = filled_log(tmp_path)
    rewrite(log, lambda lines: lines[0].update(event="forged"))
    with pytest.raises(ChainError):
        log.append(campaign_id="c", event="later", payload={})
    assert len(log.entries()) == 3


def test_non_ascii_payload_round_trips(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(campaign_id="c", event="e", payload={"text": "Holzbauklötze – größer"})
    assert log.verify()[0].payload["text"] == "Holzbauklötze – größer"
