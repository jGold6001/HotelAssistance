import asyncio
import json
import random
from datetime import date
from pathlib import Path

import pytest
from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.guest_config import GuestConfig
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.infrastructure.hotel_search.client import HotelSearchError
from hotel_assistance.infrastructure.hotel_search.simulator import (
    AUTO_OFFER_MAX,
    AUTO_OFFER_MIN,
    DEFAULT_DATASET_PATH,
    MAX_SIMULATED_OFFERS,
    SimulatedHotelSearchClient,
)

STATE = SearchState()


def ready_state(destination: str = "Haarlem", adults: int = 1, **kwargs) -> SearchState:
    """A state holding everything a search needs, so the simulator answers it."""

    return SearchState(
        destination=destination,
        check_in=date(2027, 1, 23),
        check_out=date(2027, 1, 26),
        guests=GuestConfig(adults=adults),
        **kwargs,
    )


@pytest.fixture
def dataset(tmp_path: Path):
    def build(entries: int) -> Path:
        path = tmp_path / f"hotels_{entries}.json"
        path.write_text(
            json.dumps(
                [
                    {"apartment": f"Hotel {index}", "address": f"{index} Test Street", "price": "$100-$200"}
                    for index in range(entries)
                ]
            ),
            encoding="utf-8",
        )
        return path

    return build


def dataset_none():
    """A dataset builder for cases that must never read the dataset at all."""

    def build(entries: int) -> Path:
        return Path("does-not-exist.json")

    return build


def build_client(dataset, entries: int = 4, **kwargs) -> SimulatedHotelSearchClient:
    return SimulatedHotelSearchClient(dataset_path=dataset(entries), rng=random.Random(1), **kwargs)


def search(client: SimulatedHotelSearchClient, requested: int | None, state: SearchState = STATE):
    return asyncio.run(client.search_offers(state, requested))


def test_an_incomplete_search_is_not_answered() -> None:
    result = search(build_client(dataset_none()), None)

    # Unknown, not zero: no search was run, so there is nothing to report.
    assert result.available_offers_count is None
    assert result.backend_available is False
    assert result.offers == []


def test_a_complete_search_is_answered_without_a_directive(dataset) -> None:
    result = search(build_client(dataset, entries=200), None, ready_state())

    assert result.backend_available is True
    assert AUTO_OFFER_MIN <= result.available_offers_count <= AUTO_OFFER_MAX
    assert len(result.offers) == result.available_offers_count
    assert result.note is None


def test_the_same_search_always_draws_the_same_answer(dataset) -> None:
    client = build_client(dataset, entries=200)

    first = search(client, None, ready_state())
    second = search(client, None, ready_state())

    assert first.available_offers_count == second.available_offers_count
    assert [offer.apartment for offer in first.offers] == [offer.apartment for offer in second.offers]


def test_changing_the_search_redraws_the_answer(dataset) -> None:
    client = build_client(dataset, entries=200)
    counts = {
        search(client, None, ready_state(destination=name)).available_offers_count
        for name in ("Haarlem", "Amsterdam", "Utrecht", "Delft", "Leiden")
    }

    assert len(counts) > 1


def test_a_filter_change_redraws_the_answer(dataset) -> None:
    client = build_client(dataset, entries=200)

    plain = search(client, None, ready_state())
    filtered = search(
        client, None, ready_state(filters=[AppliedFilter(filter_id="hotel.parking", value=True)])
    )

    assert plain.available_offers_count != filtered.available_offers_count


def test_a_directive_overrides_the_automatic_draw(dataset) -> None:
    result = search(build_client(dataset), 3, ready_state())

    assert result.available_offers_count == 3


def test_an_explicit_zero_is_a_result(dataset) -> None:
    result = search(build_client(dataset), 0)

    assert result.available_offers_count == 0
    assert result.backend_available is True
    assert result.offers == []


def test_the_directive_decides_how_many_offers_come_back(dataset) -> None:
    result = search(build_client(dataset), 3)

    assert result.available_offers_count == 3
    assert len(result.offers) == 3


def test_offers_within_the_dataset_are_not_repeated(dataset) -> None:
    result = search(build_client(dataset, entries=4), 4)

    assert len({offer.apartment for offer in result.offers}) == 4


def test_asking_for_more_than_the_dataset_repeats_entries(dataset) -> None:
    result = search(build_client(dataset, entries=4), 10)

    assert result.available_offers_count == 10
    assert len(result.offers) == 10
    assert {offer.apartment for offer in result.offers} == {f"Hotel {index}" for index in range(4)}


def test_a_negative_count_is_treated_as_none_found(dataset) -> None:
    result = search(build_client(dataset), -5)

    assert result.available_offers_count == 0
    assert result.offers == []


def test_an_absurd_count_is_capped_and_says_so(dataset) -> None:
    result = search(build_client(dataset, max_offers=6), 10_000)

    assert result.available_offers_count == 6
    assert len(result.offers) == 6
    assert result.note is not None and "10000" in result.note


def test_a_count_within_the_cap_carries_no_note(dataset) -> None:
    assert search(build_client(dataset), 3).note is None


def test_an_unreadable_dataset_fails_explicitly(tmp_path: Path) -> None:
    client = SimulatedHotelSearchClient(dataset_path=tmp_path / "missing.json")

    with pytest.raises(HotelSearchError):
        search(client, 1)


def test_a_malformed_dataset_fails_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "hotels.json"
    path.write_text(json.dumps([{"apartment": "No address or price"}]), encoding="utf-8")

    with pytest.raises(HotelSearchError):
        search(SimulatedHotelSearchClient(dataset_path=path), 1)


def test_the_shipped_mock_database_loads() -> None:
    client = SimulatedHotelSearchClient()

    assert DEFAULT_DATASET_PATH.exists()
    assert client.dataset_size == 100
    assert MAX_SIMULATED_OFFERS >= client.dataset_size

    result = search(client, 120)

    assert result.available_offers_count == 120
    assert len(result.offers) == 120
    assert all(offer.apartment and offer.address and offer.price for offer in result.offers)
