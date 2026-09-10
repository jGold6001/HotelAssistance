from datetime import date

from pydantic import BaseModel, model_validator


class DateRange(BaseModel):
    """A check-in/check-out date range."""

    check_in: date
    check_out: date

    @model_validator(mode="after")
    def validate_order(self) -> "DateRange":
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be strictly after check_in")
        return self
