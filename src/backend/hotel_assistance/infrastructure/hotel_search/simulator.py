"""A stand-in hotel backend for the demo, backed by a mock property database.

There is no real property backend yet, so this client simulates one. Once the
search state holds everything a real search needs - destination, stay and
guests - the simulator answers it on its own with a count drawn from the mock
database. The draw is seeded by the search state itself, so the same search
always reports the same number and changing a filter changes it.

A tester can still force the count with the ``@test_aparts`` directive typed
into the chat, which overrides the automatic draw. An incomplete search is
never answered: the count stays unknown rather than reporting zero for a
search that was never run.

The listings themselves come from a fixed JSON dataset. Asking for more
offers than the dataset holds repeats entries at random rather than
inventing properties, so nothing in the table is fabricated.
"""

import hashlib
import json
import logging
import random
from pathlib import Path

from pydantic import ValidationError

from hotel_assistance.domain.models.hotel_offer import HotelOffer
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.infrastructure.hotel_search.client import (
    HotelSearchError,
    OfferResult,
    build_search_payload,
)

logger = logging.getLogger(__name__)

# src/backend/hotel_assistance/infrastructure/hotel_search/ -> src/backend/
DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[3] / "mock_db_hotels" / "hotels_100.json"

# An upper bound on the simulated count, so a stray "@test_aparts = 1000000"
# cannot turn a test message into a multi-megabyte response.
MAX_SIMULATED_OFFERS = 500

# The range an automatic search draws from. Zero is part of it, so the
# zero-result flow shows up in the demo without anyone forcing it.
AUTO_OFFER_MIN = 0
AUTO_OFFER_MAX = 100


class SimulatedHotelSearchClient:
    """Answers a complete search from the mock database, or does what the directive says."""

    def __init__(
        self,
        dataset_path: Path | str = DEFAULT_DATASET_PATH,
        max_offers: int = MAX_SIMULATED_OFFERS,
        rng: random.Random | None = None,
    ) -> None:
        self._dataset_path = Path(dataset_path)
        self._max_offers = max_offers
        self._rng = rng or random.Random()
        self._properties: list[HotelOffer] | None = None

    async def search_offers(
        self, state: SearchState, requested_count: int | None = None
    ) -> OfferResult:
        note = None
        if requested_count is None:
            if not state.is_ready_for_search():
                # An incomplete search is not a search: an unknown count
                # leaves the reply silent about offers rather than claiming
                # none exist.
                return OfferResult()
            rng = _state_rng(state)
            count = rng.randint(AUTO_OFFER_MIN, AUTO_OFFER_MAX)
            logger.info("simulated search for a complete state returned %d offers", count)
        else:
            rng = self._rng
            count = min(max(requested_count, 0), self._max_offers)
            if requested_count > self._max_offers:
                logger.info("simulated offer count %d capped at %d", requested_count, count)
                note = f"The simulator caps a test run at {self._max_offers} offers, so {requested_count} became {count}."

        return OfferResult(
            available_offers_count=count,
            backend_available=True,
            offers=self._pick(count, rng),
            note=note,
        )

    @property
    def dataset_size(self) -> int:
        return len(self._load())

    def _pick(self, count: int, rng: random.Random) -> list[HotelOffer]:
        """Draw ``count`` properties, shuffling a fresh pass per dataset-full.

        Every property is used once before any is used twice, so a request
        that fits the dataset never repeats itself.
        """

        if count <= 0:
            return []
        pool = self._load()
        picked: list[HotelOffer] = []
        while len(picked) < count:
            batch = list(pool)
            rng.shuffle(batch)
            picked.extend(batch[: count - len(picked)])
        return picked

    def _load(self) -> list[HotelOffer]:
        if self._properties is not None:
            return self._properties

        try:
            raw = json.loads(self._dataset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HotelSearchError(f"Mock property database could not be read: {exc}") from exc
        if not isinstance(raw, list) or not raw:
            raise HotelSearchError(f"Mock property database is not a non-empty list: {self._dataset_path}")

        try:
            self._properties = [HotelOffer.model_validate(item) for item in raw]
        except ValidationError as exc:
            raise HotelSearchError(f"Mock property database has unusable entries: {exc}") from exc

        logger.info("mock property database loaded: %d properties", len(self._properties))
        return self._properties


def _state_rng(state: SearchState) -> random.Random:
    """A generator seeded by the search itself.

    Repeating a search must not repeat the dice: the same destination, stay,
    guests and filters always produce the same count and the same listings,
    while any change to them produces a new draw.
    """

    payload = json.dumps(build_search_payload(state), sort_keys=True, default=str)
    seed = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
    return random.Random(seed)
