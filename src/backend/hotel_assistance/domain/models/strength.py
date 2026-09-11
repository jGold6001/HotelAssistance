from enum import StrEnum


class FilterStrength(StrEnum):
    """How firmly the user asked for a filter.

    ``PREFERRED`` filters are the first candidates for relaxation when a
    search returns no offers; ``REQUIRED`` ones are only relaxed after those.
    """

    REQUIRED = "required"
    PREFERRED = "preferred"
