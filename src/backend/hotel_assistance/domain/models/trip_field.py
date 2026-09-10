from enum import StrEnum


class TripField(StrEnum):
    """A trip detail the validator actually changed in this turn."""

    DESTINATION = "destination"
    DATES = "dates"
    GUESTS = "guests"
