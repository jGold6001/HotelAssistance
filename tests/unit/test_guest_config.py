import pytest
from pydantic import ValidationError

from hotel_assistance.domain.models import GuestConfig


def test_defaults_to_one_adult_and_no_children() -> None:
    guests = GuestConfig()

    assert guests.adults == 1
    assert guests.children == 0


def test_rejects_zero_adults() -> None:
    with pytest.raises(ValidationError):
        GuestConfig(adults=0)


def test_rejects_negative_children() -> None:
    with pytest.raises(ValidationError):
        GuestConfig(children=-1)
