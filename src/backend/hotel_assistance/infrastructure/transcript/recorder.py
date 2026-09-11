"""Appends every chat turn to a dated JSON transcript on disk.

Recording is observability, not business logic: it runs at the API edge once
the response has been composed, and a write that fails is logged rather than
allowed to break the turn the user just had.
"""

import asyncio
import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DIRECTORY = "output"


class ChatTranscriptRecorder:
    """Writes one ``chat_json_<date>.json`` per day, holding every turn.

    The file is a JSON array rather than JSON Lines so it can be opened and
    read as-is: each turn is appended to what is already there and the whole
    array is rewritten. A demo transcript is small enough that legible output
    is worth more than the cost of the rewrite.
    """

    def __init__(self, directory: Path | str = DEFAULT_DIRECTORY, enabled: bool = True) -> None:
        self._directory = Path(directory)
        self._enabled = enabled
        # Turns of different sessions can land concurrently; the read-append-
        # write cycle has to stay one operation.
        self._lock = threading.Lock()

    def path_for(self, day: date) -> Path:
        return self._directory / f"chat_json_{day.isoformat()}.json"

    async def record(
        self,
        session_id: str,
        message: str,
        response: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Append one turn - the message and whatever the turn produced."""

        if not self._enabled:
            return

        now = datetime.now().astimezone()
        entry: dict[str, Any] = {
            "timestamp": now.isoformat(timespec="seconds"),
            "session_id": session_id,
            "user_message": message,
        }
        if response is not None:
            entry["response"] = response
        if error is not None:
            entry["error"] = error

        await asyncio.to_thread(self._append, self.path_for(now.date()), entry)

    def _append(self, path: Path, entry: dict[str, Any]) -> None:
        with self._lock:
            try:
                turns = _read_turns(path)
            except (OSError, ValueError) as exc:
                # Overwriting an unreadable transcript would destroy whatever
                # it still holds, so this turn is dropped instead.
                logger.warning("chat transcript %s is unreadable, skipping this turn: %s", path, exc)
                return
            turns.append(entry)
            try:
                _write_turns(path, turns)
            except OSError as exc:
                logger.warning("could not write chat transcript %s: %s", path, exc)


def _read_turns(path: Path) -> list[Any]:
    if not path.exists():
        return []
    turns = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(turns, list):
        raise ValueError("transcript is not a JSON array")
    return turns


def _write_turns(path: Path, turns: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and moved into place so a reader never catches a half-file.
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(turns, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
