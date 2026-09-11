import asyncio
from datetime import date

import httpx
import pytest
from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.guest_config import GuestConfig
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.infrastructure.hotel_search.client import (
    HotelSearchError,
    HttpHotelSearchClient,
    UnavailableHotelSearchClient,
    build_search_payload,
)


def build_state() -> SearchState:
    return SearchState(
        destination="Haarlem",
        check_in=date(2026, 8, 15),
        check_out=date(2026, 8, 18),
        guests=GuestConfig(adults=2, children=1),
        filters=[
            AppliedFilter(filter_id="hotel.parking", value=True),
            AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30)),
        ],
    )


def build_client(handler) -> HttpHotelSearchClient:
    transport = httpx.MockTransport(handler)
    return HttpHotelSearchClient("https://hotels.example", client=httpx.AsyncClient(transport=transport))


def test_payload_flattens_the_validated_state() -> None:
    payload = build_search_payload(build_state())

    assert payload["destination"] == "Haarlem"
    assert payload["check_in"] == "2026-08-15"
    assert payload["adults"] == 2
    assert payload["filters"] == [
        {"id": "hotel.parking", "value": True},
        {"id": "room.size_m2", "value": {"min": 30.0}},
    ]


def test_offer_count_comes_from_the_backend() -> None:
    client = build_client(lambda request: httpx.Response(200, json={"available_offers_count": 12}))

    result = asyncio.run(client.search_offers(build_state()))

    assert result.available_offers_count == 12
    assert result.backend_available is True


def test_missing_count_in_the_response_is_an_error() -> None:
    client = build_client(lambda request: httpx.Response(200, json={"hotels": []}))

    with pytest.raises(HotelSearchError):
        asyncio.run(client.search_offers(build_state()))


def test_http_failure_is_translated() -> None:
    client = build_client(lambda request: httpx.Response(503))

    with pytest.raises(HotelSearchError):
        asyncio.run(client.search_offers(build_state()))


def test_unconfigured_backend_reports_an_unknown_count() -> None:
    result = asyncio.run(UnavailableHotelSearchClient().search_offers(build_state()))

    assert result.available_offers_count is None
    assert result.backend_available is False
