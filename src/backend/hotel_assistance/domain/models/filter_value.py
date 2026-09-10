from pydantic import BaseModel, model_validator


class RangeValue(BaseModel):
    """A requested range constraint on a range filter.

    ``min`` means "at least", ``max`` means "at most"; at least one side must
    be present, otherwise the constraint carries no information.
    """

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "RangeValue":
        if self.min is None and self.max is None:
            raise ValueError("Range value must define min and/or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("Range value min cannot be greater than max")
        return self

    def describe(self, unit: str | None = None) -> str:
        suffix = f" {unit}" if unit else ""
        if self.min is not None and self.max is not None:
            return f"{_format_number(self.min)}-{_format_number(self.max)}{suffix}"
        if self.min is not None:
            return f"at least {_format_number(self.min)}{suffix}"
        return f"at most {_format_number(self.max)}{suffix}"


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


FilterValue = bool | RangeValue
