from pydantic import BaseModel

from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.date_range import DateRange
from hotel_assistance.domain.models.guest_config import GuestConfig


class SearchState(BaseModel):
    """The current, validated hotel search state for a session.

    This is the source of truth applied against the hotel search backend;
    it is only ever mutated through validated SearchPatch application.
    """

    destination: str | None = None
    dates: DateRange | None = None
    guests: GuestConfig | None = None
    filters: list[AppliedFilter] = []
