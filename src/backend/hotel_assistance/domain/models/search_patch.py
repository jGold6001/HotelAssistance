from pydantic import BaseModel

from hotel_assistance.domain.models.date_range import DateRange
from hotel_assistance.domain.models.filter_operation import FilterOperation
from hotel_assistance.domain.models.guest_config import GuestConfig


class SearchPatch(BaseModel):
    """A partial update to a SearchState, produced by the LLM from user input.

    Only fields the user actually mentioned are set; everything else stays
    untouched when the patch is applied to the current SearchState.
    """

    destination: str | None = None
    dates: DateRange | None = None
    guests: GuestConfig | None = None
    operations: list[FilterOperation] = []
    clarification_needed: str | None = None
