from typing import Any

from pydantic import BaseModel


class AppliedFilter(BaseModel):
    """A canonical filter currently active in a SearchState."""

    filter_id: str
    value: Any = None
