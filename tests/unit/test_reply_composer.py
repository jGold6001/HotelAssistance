from hotel_assistance.application.reply_composer import compose_reply
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_operation import FilterOperation
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.relaxation import RelaxationSuggestion
from hotel_assistance.domain.services.search_validator import IssueCode, ValidationIssue

REGISTRY = FilterRegistry(
    [
        FilterDefinition(id="hotel.parking", type="boolean", description="Parking"),
        FilterDefinition(id="room.size_m2", type="range", description="Room floor area", unit="m2"),
    ]
)


def compose(**overrides) -> str:
    defaults = dict(
        state=SearchState(),
        registry=REGISTRY,
        applied=[],
        issues=[],
        unmapped_requests=[],
        missing_trip_info=[],
        clarification_question=None,
        available_offers_count=None,
        relaxations=[],
        was_reset=False,
    )
    return compose_reply(**{**defaults, **overrides})


def test_applied_operations_are_named() -> None:
    reply = compose(
        applied=[
            FilterOperation(op="add", filter_id="hotel.parking", value=True),
            FilterOperation(op="add", filter_id="room.size_m2", value=RangeValue(min=30)),
        ]
    )

    assert reply.startswith("Applied: Parking and Room floor area (at least 30 m2).")


def test_removals_are_reported_separately() -> None:
    reply = compose(applied=[FilterOperation(op="remove", filter_id="hotel.parking")])

    assert "Removed: Parking." in reply


def test_a_filter_set_to_false_is_described_as_an_exclusion_not_a_removal() -> None:
    reply = compose(applied=[FilterOperation(op="add", filter_id="hotel.parking", value=False)])

    assert "Excluding properties with: Parking." in reply
    assert "Removed" not in reply


def test_conflicts_ask_the_user_to_decide() -> None:
    reply = compose(
        issues=[
            ValidationIssue(
                code=IssueCode.CONFLICT,
                message="'A' conflicts with 'B', which is already active.",
                filter_id="a",
                conflicting_filter_id="b",
            )
        ]
    )

    assert "conflicts with" in reply
    assert "which of the two you want to keep" in reply


def test_offer_count_is_only_stated_when_the_backend_supplied_one() -> None:
    assert "offers" not in compose()
    assert "matches 7 offers" in compose(available_offers_count=7)


def test_zero_offers_lists_the_relaxation_options() -> None:
    reply = compose(
        available_offers_count=0,
        relaxations=[RelaxationSuggestion(filter_id="hotel.parking", label="Parking", reason="a preference")],
    )

    assert "no offers" in reply
    assert "You could relax: Parking - a preference." in reply


def test_clarification_takes_precedence_over_a_generic_missing_info_prompt() -> None:
    reply = compose(clarification_question="Which city?", missing_trip_info=["destination"])

    assert "Which city?" in reply
    assert "where you want to stay" not in reply


def test_an_empty_turn_still_says_something_useful() -> None:
    assert "Could you say a bit more" in compose()
