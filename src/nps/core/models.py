"""Domain models shared by all modules."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class ChildSpec(Frozen):
    age_years: int = Field(ge=0, le=17)
    description: str = Field(min_length=1)


class Placement(Frozen):
    """Top-left corner of the product in the scene, in pixels."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)


class Brief(Frozen):
    campaign_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    brand: BrandSpec
    product_name: str = Field(min_length=1)
    product_category: ProductCategory
    scene: str = Field(min_length=1)
    child: ChildSpec
    width: int = Field(default=1024, ge=64, le=4096)
    height: int = Field(default=1024, ge=64, le=4096)
    seed: int = Field(ge=0, lt=2**32)
    placement: Placement


class CheckResult(Frozen):
    check: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class AssetState(str, Enum):
    PLANNED = "planned"
    GENERATED = "generated"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    APPROVED = "approved"
    SEALED = "sealed"


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
