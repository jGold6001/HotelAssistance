"""Structured contract the LLM must produce.

These models are the *only* thing an LLM adapter is allowed to return. They
describe interpreted language, never validated state: every field is treated
as untrusted until the deterministic validation layer has accepted it.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from hotel_assistance.domain.models.filter_definition import FilterType
from hotel_assistance.domain.models.filter_operation import FilterOperationType
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.strength import FilterStrength

MissingTripInfo = Literal["destination", "dates", "guests"]


class ExtractedFilter(BaseModel):
    """One filter change the user asked for, expressed over a candidate ID."""

    filter_id: str
    op: FilterOperationType
    type: FilterType
    strength: FilterStrength
    boolean_value: bool | None = None
    range_value: RangeValue | None = None

    @model_validator(mode="after")
    def validate_value_shape(self) -> "ExtractedFilter":
        if self.op is FilterOperationType.REMOVE:
            # A removal targets the filter itself; any value the model attached
            # to it carries no meaning.
            self.boolean_value = None
            self.range_value = None
            return self

        if self.type is FilterType.BOOLEAN:
            if self.boolean_value is None or self.range_value is not None:
                raise ValueError(f"Boolean filter '{self.filter_id}' must use boolean_value only")
        elif self.range_value is None or self.boolean_value is not None:
            raise ValueError(f"Range filter '{self.filter_id}' must use range_value only")
        return self


class GuestCounts(BaseModel):
    adults: int | None = None
    children: int | None = None


class TripDetails(BaseModel):
    """Trip facts as read from the message, before deterministic validation.

    Dates are plain strings because the model may echo a partially specified
    date; parsing and range validation happen in the application layer.
    """

    destination: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    guests: GuestCounts | None = None


class ExtractionResult(BaseModel):
    """Full structured interpretation of a single user message."""

    is_hotel_search_related: bool = True
    reset_requested: bool = False
    filters: list[ExtractedFilter] = Field(default_factory=list)
    unmapped_requests: list[str] = Field(default_factory=list)
    trip: TripDetails = Field(default_factory=TripDetails)
    missing_trip_info: list[MissingTripInfo] = Field(default_factory=list)
    clarification_question: str | None = None
