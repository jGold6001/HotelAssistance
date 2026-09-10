"""The ``@test_aparts`` directive: a manual override for the demo backend.

There is no real property backend, so a tester states how many offers the
simulated one should return by typing ``@test_aparts = 32`` in the chat. The
directive is a test instrument, not a search request: it is stripped out of
the message before anything interprets language, and it never touches the
search state.

A message with no directive means zero offers, which is the whole point of
the default - the zero-result path is the one worth exercising by accident.
"""

import re

# ``@aparts`` is accepted as a shorthand for the same directive, and the
# count may be omitted ("@test_aparts") to mean zero.
DIRECTIVE_PATTERN = re.compile(r"@(?:test_)?aparts\s*(?:=\s*(-?\d+))?", re.IGNORECASE)


def extract_offer_directive(message: str) -> tuple[str, int | None]:
    """Split a message into what the user asked for and what the tester forced.

    Returns the message with every directive removed, and the requested offer
    count (``None`` when the message contains no directive at all). The last
    directive wins, so correcting a number in the same message works. A
    negative count is passed through as written and clamped by the backend.
    """

    matches = list(DIRECTIVE_PATTERN.finditer(message))
    if not matches:
        return message.strip(), None

    requested = matches[-1].group(1)
    cleaned = DIRECTIVE_PATTERN.sub(" ", message)
    return " ".join(cleaned.split()), int(requested) if requested else 0
