"""Builds the assistant's reply from the deterministic outcome.

The reply is assembled from what actually happened - applied operations,
rejected ones, the resulting state and the backend's offer count - so it can
never claim a filter was set when validation refused it. Only the
clarification question itself comes from the LLM, because phrasing a question
is a language task.

Every reply that asks something also says what the search still holds. A
follow-up turn ("I need something in May") only makes sense against the
context of earlier ones, so the user has to be able to see that the context
survived without repeating themselves.
"""

from datetime import date

from hotel_assistance.domain.models.filter_operation import (
    FilterOperation,
    FilterOperationType,
)
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.guest_config import GuestConfig
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.relaxation import RelaxationSuggestion
from hotel_assistance.domain.services.search_validator import (
    IssueCode,
    TripField,
    ValidationIssue,
)

OUT_OF_SCOPE_REPLY = (
    "I can only help with hotel-search filters - destination, dates, guests, "
    "and property or room features. Tell me what you are looking for in a hotel "
    "and I will set the search up."
)

MISSING_LABELS = {
    "destination": "where you want to stay",
    "dates": "your check-in and check-out dates",
    "guests": "how many people are travelling",
}

# Enough to show the user what was dropped without turning the reply into a
# list; the full set is still returned in the API response.
MAX_LISTED_UNMAPPED = 3

# Month names are fixed rather than taken from strftime, which follows the
# process locale and would otherwise leak a non-English reply.
MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def compose_reply(
    state: SearchState,
    registry: FilterRegistry,
    applied: list[FilterOperation],
    applied_trip: list[TripField],
    issues: list[ValidationIssue],
    unmapped_requests: list[str],
    clarification_question: str | None,
    available_offers_count: int | None,
    relaxations: list[RelaxationSuggestion],
    was_reset: bool,
    destination_hint: str | None = None,
    date_hint: str | None = None,
    offers_note: str | None = None,
) -> str:
    parts: list[str] = []

    if was_reset:
        parts.append("Cleared the search. Starting fresh.")

    # The model's question wins when it has one, because it can name the thing
    # the user was vague about; the state-derived question is the fallback.
    question = clarification_question or _missing_info_question(state, destination_hint, date_hint)

    context = _describe_context(state, applied_trip, asking=question is not None)
    if context:
        parts.append(context)

    parts.extend(_describe_applied(applied, registry))
    parts.extend(issue.message for issue in issues if issue.code is not IssueCode.NOT_APPLIED)

    if any(issue.code is IssueCode.CONFLICT for issue in issues):
        parts.append("Tell me which of the two you want to keep and I will switch it over.")

    if unmapped_requests:
        parts.append(_describe_unmapped(unmapped_requests))

    parts.extend(_describe_offers(available_offers_count, relaxations, offers_note))

    if question:
        parts.append(question)

    if not parts:
        parts.append("I did not find anything to change in the search. Could you say a bit more about what you want?")

    return " ".join(parts)


def compose_simulated_search_reply(
    available_offers_count: int | None,
    relaxations: list[RelaxationSuggestion],
    offers_note: str | None = None,
) -> str:
    """Answer a bare ``@test_aparts`` directive.

    Nothing about the search changed, so the reply says only what the backend
    reported back - and says so without a model call, like every other
    deterministic part of a reply.
    """

    parts = _describe_offers(available_offers_count, relaxations, offers_note)
    if not parts:
        return "The hotel backend is unavailable, so I cannot say how many offers match."
    return " ".join(parts)


def _describe_offers(
    available_offers_count: int | None,
    relaxations: list[RelaxationSuggestion],
    note: str | None = None,
) -> list[str]:
    """Report the backend's answer, or stay silent when it has not given one."""

    if available_offers_count is None:
        return []
    if available_offers_count == 0:
        parts = ["The hotel backend finds no offers for this search."]
        if relaxations:
            options = "; ".join(f"{item.label} - {item.reason}" for item in relaxations)
            parts.append(f"You could relax: {options}.")
    else:
        plural = "" if available_offers_count == 1 else "s"
        parts = [f"The hotel backend currently matches {available_offers_count} offer{plural}."]
    if note:
        parts.append(note)
    return parts


def compose_out_of_scope_reply(state: SearchState) -> str:
    """Refuse the request without throwing away the search behind it."""

    summary = _summarise_state(state, include_filters=True)
    if not summary:
        return OUT_OF_SCOPE_REPLY
    return f"{OUT_OF_SCOPE_REPLY} Your current search is unchanged: {summary}."


def _describe_context(state: SearchState, applied_trip: list[TripField], asking: bool) -> str | None:
    """Say what the search holds now, in the form this turn calls for.

    When a question is coming, the point is continuity: the user must see that
    answering one question is all that is left. Otherwise the point is
    confirmation of the trip details this turn actually changed.
    """

    if asking:
        summary = _summarise_state(state, include_filters=True)
        return f"I still have {summary}." if summary else None

    if not applied_trip:
        return None
    # Filters are spelled out by _describe_applied, so they are left out here.
    summary = _summarise_state(state, include_filters=False)
    return f"Got it: {summary}." if summary else None


def _summarise_state(state: SearchState, include_filters: bool) -> str:
    bits: list[str] = []
    if state.destination:
        bits.append(state.destination)
    dates = _describe_dates(state)
    if dates:
        bits.append(dates)
    if state.guests:
        bits.append(_describe_guests(state.guests))
    if include_filters and state.filters:
        count = len(state.filters)
        bits.append(f"{count} saved preference{'' if count == 1 else 's'}")
    return _join_readable(bits) if bits else ""


def _describe_dates(state: SearchState) -> str | None:
    """Render whatever part of the stay is known, in a compact form."""

    check_in, check_out = state.check_in, state.check_out
    if check_in and check_out:
        if (check_in.year, check_in.month) == (check_out.year, check_out.month):
            return f"{check_in.day}-{check_out.day} {_month(check_in)} {check_in.year}"
        if check_in.year == check_out.year:
            return f"{check_in.day} {_month(check_in)} - {_format_date(check_out)}"
        return f"{_format_date(check_in)} - {_format_date(check_out)}"
    if check_in:
        return f"from {_format_date(check_in)}"
    if check_out:
        return f"until {_format_date(check_out)}"
    return None


def _describe_guests(guests: GuestConfig) -> str:
    bits = [f"{guests.adults} adult{'' if guests.adults == 1 else 's'}"]
    if guests.children:
        bits.append(f"{guests.children} child{'' if guests.children == 1 else 'ren'}")
    return " and ".join(bits)


def _missing_info_question(
    state: SearchState,
    destination_hint: str | None,
    date_hint: str | None,
) -> str | None:
    """Ask for the trip facts the state is still missing, and only those.

    The hints are the user's own words for a detail they moved without pinning
    down ("in May"), so echoing them back shows the request was understood
    rather than ignored.
    """

    needed: list[str] = []
    for field in state.missing_trip_info():
        if field == "destination":
            needed.append(_with_hint(MISSING_LABELS[field], destination_hint))
        elif field == "dates":
            needed.append(_with_hint(_dates_label(state), date_hint))
        else:
            needed.append(MISSING_LABELS[field])

    if not needed:
        return None
    return f"To run the search I still need {_join_readable(needed)}."


def _dates_label(state: SearchState) -> str:
    if state.check_in and not state.check_out:
        return "your check-out date"
    if state.check_out and not state.check_in:
        return "your check-in date"
    return MISSING_LABELS["dates"]


def _with_hint(label: str, hint: str | None) -> str:
    hint = (hint or "").strip()
    return f'{label} (you said "{hint}")' if hint else label


def _describe_unmapped(requests: list[str]) -> str:
    listed = "; ".join(requests[:MAX_LISTED_UNMAPPED])
    remaining = len(requests) - MAX_LISTED_UNMAPPED
    if remaining > 0:
        listed = f"{listed}, and {remaining} more"
    return f"I could not map these to a supported filter, so they are not part of the search: {listed}."


def _describe_applied(applied: list[FilterOperation], registry: FilterRegistry) -> list[str]:
    """Report the three outcomes separately.

    Dropping a filter and requiring its absence are different search states, so
    they must not be described with the same word.
    """

    added: list[str] = []
    removed: list[str] = []
    excluded: list[str] = []
    for operation in applied:
        definition = registry.get(operation.filter_id)
        if definition is None:
            continue
        if operation.op is FilterOperationType.REMOVE:
            removed.append(definition.description)
        elif isinstance(operation.value, RangeValue):
            added.append(f"{definition.description} ({operation.value.describe(definition.unit)})")
        elif operation.value is False:
            excluded.append(definition.description)
        else:
            added.append(definition.description)

    parts: list[str] = []
    if added:
        parts.append(f"Applied: {_join_readable(added)}.")
    if removed:
        parts.append(f"Removed: {_join_readable(removed)}.")
    if excluded:
        parts.append(f"Excluding properties with: {_join_readable(excluded)}.")
    return parts


def _format_date(value: date) -> str:
    return f"{value.day} {_month(value)} {value.year}"


def _month(value: date) -> str:
    return MONTH_NAMES[value.month - 1]


def _join_readable(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"
