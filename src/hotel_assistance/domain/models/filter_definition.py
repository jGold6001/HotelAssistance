from enum import StrEnum

from pydantic import BaseModel


class FilterType(StrEnum):
    BOOLEAN = "boolean"
    RANGE = "range"


class RangeBounds(BaseModel):
    """Inclusive lower/upper bounds for a range filter's value."""

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
