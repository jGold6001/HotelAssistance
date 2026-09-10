"""A trip detail the user replaced without naming a replacement.

Deliberately not part of SearchState: an open question is not a validated
fact, and SearchState is what reaches the hotel backend. It lives on the
session for as long as the question stays open, so "actually, keep August"
can be answered from a remembered value instead of from the model's reading
of the transcript.
"""

from datetime import date

from pydantic import BaseModel

from hotel_assistance.domain.models.trip_field import TripField


class PendingTripChange(BaseModel):
    field: TripField
    hint: str
    previous_destination: str | None = None
    previous_check_in: date | None = None
    previous_check_out: date | None = None

    def has_previous_value(self) -> bool:
        return bool(self.previous_destination or self.previous_check_in or self.previous_check_out)
