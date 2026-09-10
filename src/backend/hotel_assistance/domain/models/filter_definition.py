from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class FilterType(StrEnum):
    BOOLEAN = "boolean"
    RANGE = "range"


class RangeBounds(BaseModel):
    """Inclusive lower/upper bounds a range filter's value must stay within."""

    min: float | None = None
    max: float | None = None


class FilterDefinition(BaseModel):
    """A canonical, registry-defined hotel-search filter."""

    id: str
    type: FilterType
    description: str
    aliases: list[str] = []
    unit: str | None = None
    bounds: RangeBounds | None = None
    conflicts_with: list[str] = []
    source: dict[str, Any] | None = None
    """Provenance metadata from the hotel backend's facility catalog.

    Never sent to the LLM and never used for matching; kept so a canonical ID
    can be traced back to the backend facility it was derived from.
    """
