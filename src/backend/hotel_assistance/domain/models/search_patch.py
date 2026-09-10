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
    """

    destination: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    guests: GuestConfig | None = None
    operations: list[FilterOperation] = []
    reset: bool = False

    def is_empty(self) -> bool:
        return not (
            self.reset
            or self.destination
            or self.check_in
            or self.check_out
            or self.guests
            or self.operations
        )
