"""Engines by name, so callers never import a concrete adapter."""

from __future__ import annotations

from nps.engine.base import Engine

ENGINE_NAMES = ("mock", "flux2-klein-4b")


def engine_by_name(name: str) -> Engine:
    if name == "mock":
        from nps.engine.mock import MockEngine

        return MockEngine()
    if name == "flux2-klein-4b":
        from nps.engine.flux2_klein import Flux2KleinConfig, Flux2KleinEngine

        return Flux2KleinEngine(Flux2KleinConfig.from_env())
    raise ValueError(f"unknown engine '{name}', expected one of {list(ENGINE_NAMES)}")
