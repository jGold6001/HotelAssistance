"""A stand-in hotel backend for the demo, backed by a mock property database.

There is no real property backend yet, so this client simulates one. It
cannot match filters, which is exactly why the number of offers is not its
decision: the count comes from the ``@test_aparts`` directive the tester
types into the chat, and is zero when no directive is present.

The listings themselves come from a fixed JSON dataset. Asking for more
offers than the dataset holds repeats entries at random rather than
inventing properties, so nothing in the table is fabricated.
"""

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
)

logger = logging.getLogger(__name__)

# src/backend/hotel_assistance/infrastructure/hotel_search/ -> src/backend/
DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[3] / "mock_db_hotels" / "hotels_100.json"

# An upper bound on the simulated count, so a stray "@test_aparts = 1000000"
# cannot turn a test message into a multi-megabyte response.
MAX_SIMULATED_OFFERS = 500


class SimulatedHotelSearchClient:
    """Returns as many mock properties as the test directive asked for."""

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
        count = min(max(requested_count or 0, 0), self._max_offers)
        note = None
        if requested_count is not None and requested_count > self._max_offers:
            logger.info("simulated offer count %d capped at %d", requested_count, count)
            note = f"The simulator caps a test run at {self._max_offers} offers, so {requested_count} became {count}."
        return OfferResult(
            available_offers_count=count,
            backend_available=True,
            offers=self._pick(count),
            note=note,
        )

    @property
    def dataset_size(self) -> int:
        return len(self._load())

    def _pick(self, count: int) -> list[HotelOffer]:
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
            self._rng.shuffle(batch)
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
