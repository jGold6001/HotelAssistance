from datetime import date

from pydantic import BaseModel

from hotel_assistance.domain.models.filter_operation import FilterOperation
from hotel_assistance.domain.models.guest_config import GuestConfig


class SearchPatch(BaseModel):
    """A partial, deterministically built update to a SearchState.

    Only fields the user actually mentioned are set; everything else stays
    untouched when the patch is applied to the current SearchState. The patch
    is never produced directly by the LLM: it is derived from an
    ExtractionResult after the referenced filter IDs have been checked.

    ``clear_destination`` and ``clear_dates`` express the case where the user
    replaced a trip detail without saying what with ("something in May"): the
    old value is no longer what they want, so it must not survive into the
    search, but no new value is known yet either.
    """

    destination: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    guests: GuestConfig | None = None
    operations: list[FilterOperation] = []
    reset: bool = False
    clear_destination: bool = False
    clear_dates: bool = False

    def is_empty(self) -> bool:
        return not (
            self.reset
            or self.destination
            or self.check_in
            or self.check_out
            or self.guests
            or self.operations
            or self.clear_destination
            or self.clear_dates
        )
