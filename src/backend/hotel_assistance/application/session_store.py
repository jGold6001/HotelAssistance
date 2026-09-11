"""In-memory session state.

Sufficient for the demo scope: state lives for the lifetime of the process
and is not shared between workers.
"""

from dataclasses import dataclass, field

from hotel_assistance.domain.models.chat import ChatRole, ChatTurn
from hotel_assistance.domain.models.pending_change import PendingTripChange
from hotel_assistance.domain.models.search_state import SearchState

MAX_HISTORY_TURNS = 12


@dataclass
class Session:
    state: SearchState = field(default_factory=SearchState)
    history: list[ChatTurn] = field(default_factory=list)
    # The trip detail the user replaced but has not pinned down yet, if any.
    pending: PendingTripChange | None = None

    def record(self, role: ChatRole, content: str) -> None:
        self.history.append(ChatTurn(role=role, content=content))
        del self.history[:-MAX_HISTORY_TURNS]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        return self._sessions.setdefault(session_id, Session())

    def reset(self, session_id: str) -> Session:
        session = Session()
        self._sessions[session_id] = session
        return session
