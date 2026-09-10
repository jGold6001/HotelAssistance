"""Integration with the non-AI hotel backend.

The backend is the only source of truth for offers, prices, availability and
``available_offers_count``. When no backend is configured the count is
reported as unknown (``None``) - it is never estimated, and never invented.
"""

import logging
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.search_state import SearchState

logger = logging.getLogger(__name__)


class HotelSearchError(Exception):
    """Raised when the hotel backend cannot be reached or answers unusably."""


class OfferCount(BaseModel):
    """How many offers the backend matches, or ``None`` when it is unknown."""

    available_offers_count: int | None = None
    backend_available: bool = False


class HotelSearchClient(Protocol):
    async def count_offers(self, state: SearchState) -> OfferCount: ...


class UnavailableHotelSearchClient:
    """Used when no hotel backend is configured.

    Reports the offer count as unknown so nothing downstream can present a
    fabricated number as if it came from the backend.
    """

    async def count_offers(self, state: SearchState) -> OfferCount:
        return OfferCount(available_offers_count=None, backend_available=False)


class HttpHotelSearchClient:
    """Queries a hotel backend over HTTP for the matching-offer count."""

    def __init__(self, base_url: str, timeout: float = 10.0, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    async def count_offers(self, state: SearchState) -> OfferCount:
        payload = build_search_payload(state)
        try:
            if self._client is not None:
                response = await self._client.post(f"{self._base_url}/search/count", json=payload)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(f"{self._base_url}/search/count", json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HotelSearchError(f"Hotel backend request failed: {exc}") from exc

        count = body.get("available_offers_count")
        if not isinstance(count, int):
            raise HotelSearchError(f"Hotel backend returned no usable available_offers_count: {body!r}")
        return OfferCount(available_offers_count=count, backend_available=True)


def build_search_payload(state: SearchState) -> dict[str, Any]:
    """Translate validated search state into a backend query payload."""

    return {
        "destination": state.destination,
        "check_in": state.check_in.isoformat() if state.check_in else None,
        "check_out": state.check_out.isoformat() if state.check_out else None,
        "adults": state.guests.adults if state.guests else None,
        "children": state.guests.children if state.guests else None,
        "filters": [
            {
                "id": applied.filter_id,
                "value": applied.value.model_dump(exclude_none=True)
                if isinstance(applied.value, RangeValue)
                else applied.value,
            }
            for applied in state.filters
        ],
    }
