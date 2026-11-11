"""Safety gate interface and the two step-0 implementations.

Neither is a real classifier. `BlockAllGate` is the default, so a deployment
that forgot to configure a gate delivers nothing. `MockOnlyGate` exists for the
end-to-end run with the mock engine and refuses output from any other engine.
"""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from nps.core.models import CheckResult, Manifest
from nps.engine.mock import MOCK_ENGINE_NAME


class SafetyGate(Protocol):
    name: str
    production: bool

    def evaluate(self, image: Image.Image, manifest: Manifest) -> CheckResult: ...


class BlockAllGate:
    name = "block_all"
    production = False

    def evaluate(self, image: Image.Image, manifest: Manifest) -> CheckResult:
        return CheckResult(
            check="safety_gate",
            passed=False,
            details={"gate": self.name, "reason": "no safety classifier configured"},
        )


class MockOnlyGate:
    name = "mock_only"
    production = False

    def evaluate(self, image: Image.Image, manifest: Manifest) -> CheckResult:
        is_mock = manifest.engine == MOCK_ENGINE_NAME
        reason = (
            "mock engine output contains no people"
            if is_mock
            else f"engine '{manifest.engine}' requires a real safety classifier"
        )
        return CheckResult(
            check="safety_gate", passed=is_mock, details={"gate": self.name, "reason": reason}
        )


_GATES: dict[str, type] = {BlockAllGate.name: BlockAllGate, MockOnlyGate.name: MockOnlyGate}


def gate_by_name(name: str) -> SafetyGate:
    try:
        return _GATES[name]()
    except KeyError:
        raise ValueError(f"unknown safety gate '{name}', expected one of {sorted(_GATES)}") from None
