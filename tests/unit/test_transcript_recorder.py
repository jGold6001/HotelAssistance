import asyncio
import json
from datetime import date

from hotel_assistance.infrastructure.transcript.recorder import ChatTranscriptRecorder


def test_turns_accumulate_in_one_file_per_day(tmp_path) -> None:
    recorder = ChatTranscriptRecorder(directory=tmp_path / "output")

    asyncio.run(recorder.record("s1", "first", response={"reply": "ok"}))
    asyncio.run(recorder.record("s2", "second", response={"reply": "ok"}))

    path = recorder.path_for(date.today())
    assert path.name == f"chat_json_{date.today().isoformat()}.json"
    turns = json.loads(path.read_text(encoding="utf-8"))
    assert [(turn["session_id"], turn["user_message"]) for turn in turns] == [
        ("s1", "first"),
        ("s2", "second"),
    ]
    assert all(turn["timestamp"] for turn in turns)


def test_non_ascii_messages_are_kept_readable(tmp_path) -> None:
    recorder = ChatTranscriptRecorder(directory=tmp_path)

    asyncio.run(recorder.record("default", "готель у Львові", response={"reply": "ok"}))

    assert "готель у Львові" in recorder.path_for(date.today()).read_text(encoding="utf-8")


def test_a_disabled_recorder_writes_nothing(tmp_path) -> None:
    recorder = ChatTranscriptRecorder(directory=tmp_path, enabled=False)

    asyncio.run(recorder.record("default", "first", response={"reply": "ok"}))

    assert not recorder.path_for(date.today()).exists()


def test_an_unreadable_transcript_is_left_alone(tmp_path) -> None:
    """Overwriting it would destroy whatever it still holds."""

    recorder = ChatTranscriptRecorder(directory=tmp_path)
    path = recorder.path_for(date.today())
    path.write_text("{ not json", encoding="utf-8")

    asyncio.run(recorder.record("default", "first", response={"reply": "ok"}))

    assert path.read_text(encoding="utf-8") == "{ not json"
