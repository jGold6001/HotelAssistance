"""Integration with the non-AI hotel backend.

The backend is the only source of truth for offers, prices, availability and
``available_offers_count``. When no backend is configured the count is
reported as unknown (``None``) - it is never estimated, and never invented.
"""

import logging
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.hotel_offer import HotelOffer
from hotel_assistance.domain.models.search_state import SearchState

logger = logging.getLogger(__name__)


class HotelSearchError(Exception):
    """Raised when the hotel backend cannot be reached or answers unusably."""


class OfferResult(BaseModel):
    """What the backend matched: how many offers, and the properties behind them.

    ``available_offers_count`` is ``None`` when the count is unknown, which is
    not the same as zero. ``offers`` holds whatever listings the backend
    returned alongside the count; it may be empty even for a non-zero count.
    ``note`` is set when the backend answered something other than what was
    asked, so the reply can say so instead of quietly showing a different
    number.
    """

    available_offers_count: int | None = None
    backend_available: bool = False
    offers: list[HotelOffer] = []
    note: str | None = None


class HotelSearchClient(Protocol):
    async def search_offers(
        self, state: SearchState, requested_count: int | None = None
    ) -> OfferResult:
        """Ask the backend what the validated state matches.

        ``requested_count`` is the demo simulator's ``@test_aparts`` override.
        A real backend counts for itself and ignores it.
        """
        ...


class UnavailableHotelSearchClient:
    """Used when no hotel backend is configured.

    Reports the offer count as unknown so nothing downstream can present a
    fabricated number as if it came from the backend.
    """

    async def search_offers(
        self, state: SearchState, requested_count: int | None = None
    ) -> OfferResult:
        return OfferResult(available_offers_count=None, backend_available=False)


class HttpHotelSearchClient:
    """Queries a hotel backend over HTTP for the matching offers."""

    def __init__(self, base_url: str, timeout: float = 10.0, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client

    async def search_offers(
        self, state: SearchState, requested_count: int | None = None
    ) -> OfferResult:
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
        return OfferResult(
            available_offers_count=count,
            backend_available=True,
            offers=_parse_offers(body.get("offers")),
        )


def _parse_offers(raw: Any) -> list[HotelOffer]:
    """Read the optional listing part of a backend response.

    The count is the contract; listings are a bonus, so a backend that omits
    them or spells one of them wrong loses the listing, not the whole answer.
    """

    if not isinstance(raw, list):
        return []
    offers: list[HotelOffer] = []
    for item in raw:
        try:
            offers.append(HotelOffer.model_validate(item))
        except ValidationError:
            logger.warning("hotel backend returned an unusable offer entry: %r", item)
    return offers


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
