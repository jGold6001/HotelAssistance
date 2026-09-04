from datetime import date

import pytest
from pydantic import ValidationError

from hotel_assistance.domain.models import DateRange


def test_valid_date_range_is_accepted() -> None:
    date_range = DateRange(check_in=date(2026, 5, 1), check_out=date(2026, 5, 5))

    assert date_range.check_in < date_range.check_out


def test_check_out_before_check_in_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DateRange(check_in=date(2026, 5, 5), check_out=date(2026, 5, 1))


def test_equal_check_in_and_check_out_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DateRange(check_in=date(2026, 5, 1), check_out=date(2026, 5, 1))
