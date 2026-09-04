from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class FilterOperationType(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"


class FilterOperation(BaseModel):
    """A single add/remove/update instruction targeting one canonical filter."""

    op: FilterOperationType
    filter_id: str
    value: Any = None
