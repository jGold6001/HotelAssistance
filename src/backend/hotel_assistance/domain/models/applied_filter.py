from pydantic import BaseModel

from hotel_assistance.domain.models.filter_value import FilterValue
from hotel_assistance.domain.models.strength import FilterStrength


class AppliedFilter(BaseModel):
    """A canonical filter currently active in a SearchState."""

    filter_id: str
    value: FilterValue
    strength: FilterStrength = FilterStrength.REQUIRED
