"""Domain models shared by all modules."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProductCategory(str, Enum):
    CLOTHING = "clothing"
    TOYS = "toys"
    FOOD = "food"
    FURNITURE = "furniture"
    STROLLERS_AND_CAR_SEATS = "strollers_and_car_seats"
    OTHER = "other"
    # Known categories that are excluded in v1. They are part of the schema so
    # that a brief naming them is rejected with a clear reason, not a parse error.
    DIAPERS = "diapers"
    BATH = "bath"
    SWIMWEAR = "swimwear"
    UNDERWEAR = "underwear"


class BrandSpec(Frozen):
    name: str = Field(min_length=1)
    colors: list[str] = Field(default_factory=list, description="Brand colours as #RRGGBB")


class PersonSpec(Frozen):
    """A synthetic person in the image. Only children exist so far."""

    age_years: int = Field(ge=0, le=17)
    description: str = Field(min_length=1)
    # A registered brand child. Both are given together or not at all.
    identity_id: str | None = None
    identity_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _identity_is_complete(self) -> "PersonSpec":
        if (self.identity_id is None) != (self.identity_version is None):
            raise ValueError("identity_id and identity_version must be given together")
        return self


class Placement(Frozen):
    """Top-left corner of the product in the scene, in pixels."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)


_ID = r"^[a-z0-9][a-z0-9_-]{1,63}$"


class MotifSpec(Frozen):
    motif_id: str = Field(pattern=_ID)
    description: str | None = Field(default=None, min_length=1)
    placement: Placement


class ShootingBrief(Frozen):
    """One shooting: what all motifs share, plus the motifs themselves.

    A single image is a shooting with one motif.
    """

    campaign_id: str = Field(pattern=_ID)
    shooting_id: str = Field(pattern=_ID)
    brand: BrandSpec
    product_name: str = Field(min_length=1)
    product_category: ProductCategory
    scene: str = Field(min_length=1)
    persons: list[PersonSpec] = Field(min_length=1)
    width: int = Field(default=1024, ge=64, le=4096)
    height: int = Field(default=1024, ge=64, le=4096)
    base_seed: int = Field(ge=0, lt=2**32)
    variants_per_motif: int = Field(default=6, ge=6, le=24)
    motifs: list[MotifSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _motif_ids_are_unique(self) -> "ShootingBrief":
        ids = [motif.motif_id for motif in self.motifs]
        if len(ids) != len(set(ids)):
            raise ValueError("motif ids must be unique within a shooting")
        return self

    def motif(self, motif_id: str) -> MotifSpec:
        for motif in self.motifs:
            if motif.motif_id == motif_id:
                return motif
        raise KeyError(motif_id)


class CheckResult(Frozen):
    check: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class AssetState(str, Enum):
    """State of one generated variant."""

    PLANNED = "planned"
    GENERATED = "generated"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    APPROVED = "approved"
    SEALED = "sealed"


class VersionStatus(str, Enum):
    """State of a version (V1, V2, ...) of a motif on its way to the client."""

    SEALED = "sealed"
    RELEASED = "released"
    CUSTOMER_APPROVED = "customer_approved"
    CHANGES_REQUESTED = "changes_requested"


class Manifest(Frozen):
    """Everything needed to regenerate an image."""

    engine: str
    engine_version: str
    weights_sha256: str | None
    model_revision: str | None
    prompt: str
    seed: int
    width: int
    height: int
    request_sha256: str
    output_sha256: str
    libraries: dict[str, str]
    runtime: dict[str, str]
