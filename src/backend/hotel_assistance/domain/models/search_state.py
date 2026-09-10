from datetime import date

from pydantic import BaseModel

from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.date_range import DateRange
from hotel_assistance.domain.models.guest_config import GuestConfig


class SearchState(BaseModel):
    """The current, validated hotel search state for a session.

    This is the source of truth applied against the hotel search backend;
    it is only ever mutated through validated SearchPatch application.

    Check-in and check-out are stored separately so a half-specified stay
    survives until the user supplies the other side; ``date_range`` exposes
    them as a validated DateRange once both are known.
    """

    destination: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    guests: GuestConfig | None = None
    filters: list[AppliedFilter] = []

    def date_range(self) -> DateRange | None:
        if self.check_in is None or self.check_out is None:
            return None
        return DateRange(check_in=self.check_in, check_out=self.check_out)

    def filter_by_id(self, filter_id: str) -> AppliedFilter | None:
        return next((item for item in self.filters if item.filter_id == filter_id), None)

    def is_ready_for_search(self) -> bool:
        return bool(self.destination and self.date_range() and self.guests)

    def missing_trip_info(self) -> list[str]:
        """Required trip facts still absent, in the order they are asked for.

        Derived from the validated state rather than reported by the model, so
        the assistant can never ask again for something it already holds.
        """

        missing: list[str] = []
        if not self.destination:
            missing.append("destination")
        if self.date_range() is None:
            missing.append("dates")
        if self.guests is None:
            missing.append("guests")
        return missing
