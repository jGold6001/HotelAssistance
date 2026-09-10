import asyncio
import json
import random
from pathlib import Path

import pytest
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.infrastructure.hotel_search.client import HotelSearchError
from hotel_assistance.infrastructure.hotel_search.simulator import (
    DEFAULT_DATASET_PATH,
    MAX_SIMULATED_OFFERS,
    SimulatedHotelSearchClient,
)

STATE = SearchState()


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


def build_client(dataset, entries: int = 4, **kwargs) -> SimulatedHotelSearchClient:
    return SimulatedHotelSearchClient(dataset_path=dataset(entries), rng=random.Random(1), **kwargs)


def search(client: SimulatedHotelSearchClient, requested: int | None):
    return asyncio.run(client.search_offers(STATE, requested))


def test_no_directive_means_no_offers(dataset) -> None:
    result = search(build_client(dataset), None)

    assert result.available_offers_count == 0
    assert result.offers == []
    # The simulator is reachable; it simply matched nothing.
    assert result.backend_available is True


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
