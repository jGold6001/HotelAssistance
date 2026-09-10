from enum import StrEnum

from pydantic import BaseModel

from hotel_assistance.domain.models.filter_value import FilterValue
from hotel_assistance.domain.models.strength import FilterStrength


class FilterOperationType(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"


class FilterOperation(BaseModel):
    """A single add/remove/update instruction targeting one canonical filter.

    ``value`` is required for ``add``/``update`` and ignored for ``remove``.
    """

    op: FilterOperationType
    filter_id: str
    value: FilterValue | None = None
    strength: FilterStrength = FilterStrength.REQUIRED
