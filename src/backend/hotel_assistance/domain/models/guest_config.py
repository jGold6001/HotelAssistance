from pydantic import BaseModel, Field


class GuestConfig(BaseModel):
    """Number of adults and children for a hotel search."""

    adults: int = Field(default=1, ge=1)
    children: int = Field(default=0, ge=0)
