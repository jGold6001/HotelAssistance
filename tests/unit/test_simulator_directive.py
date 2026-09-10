import pytest
from hotel_assistance.application.simulator_directive import extract_offer_directive


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("@test_aparts = 32", 32),
        ("@test_aparts=32", 32),
        ("@TEST_APARTS = 7", 7),
        ("@aparts = 5", 5),
        ("@test_aparts", 0),
        ("@test_aparts = 0", 0),
        ("@test_aparts = -4", -4),
    ],
)
def test_directive_forms_are_recognised(message: str, expected: int) -> None:
    remaining, requested = extract_offer_directive(message)

    assert requested == expected
    assert remaining == ""


def test_a_message_without_the_directive_is_untouched() -> None:
    remaining, requested = extract_offer_directive("Quiet hotel in Haarlem")

    assert requested is None
    assert remaining == "Quiet hotel in Haarlem"


def test_the_directive_is_stripped_out_of_a_real_request() -> None:
    remaining, requested = extract_offer_directive("Quiet hotel in Haarlem @test_aparts = 12 with parking")

    assert requested == 12
    assert remaining == "Quiet hotel in Haarlem with parking"


def test_the_last_directive_wins() -> None:
    remaining, requested = extract_offer_directive("@test_aparts = 3 @test_aparts = 9")

    assert requested == 9
    assert remaining == ""
