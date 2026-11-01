"""Tests for saved conversations (conversations.py): files in a temporary folder."""

from tgv_analyst import conversations
from tgv_analyst.events import (
    ConfidenceInterval, FinalAnswer, GuardVerdict, Reasoning, Thinking, ToolCall, ToolResult,
)

EVENTS = [
    Thinking(step=1),
    Reasoning(step=1, text="je calcule"),
    ToolCall(call_id=1, code="print(1)"),
    ToolResult(call_id=1, output="1\n", numbers=[1.0], error=None),
    ConfidenceInterval(label="640 / 6704", estimate=0.0955, low=0.0886, high=0.1028),
    GuardVerdict(passed=True, checked=["1"], rejected=[], will_retry=False),
    FinalAnswer(text="Il y a 1 ligne.", sources={"1": 1}),
]
RESULT = {"status": "ok", "answer": "x", "trace": {"turns": 2, "seconds": 3.5, "tokens": 120, "steps": ["big"]}}


def test_every_event_type_survives_a_round_trip():
    for event in EVENTS:
        assert conversations.event_from_dict(conversations.event_to_dict(event)) == event


def test_save_load_and_list(tmp_path):
    conversation = conversations.new_conversation()
    conversations.add_question(conversation, "Une question très longue " * 5, EVENTS, RESULT)
    conversations.add_question(conversation, "Annulée", EVENTS[:2], None, "Question annulée.")
    conversations.save(conversation, tmp_path)

    loaded = conversations.load(conversation["id"], tmp_path)
    assert loaded == conversation
    assert len(loaded["title"]) == conversations.TITLE_LENGTH and loaded["title"].endswith("…")
    assert "steps" not in loaded["questions"][0]["result"]["trace"]  # only what the summary needs
    assert loaded["questions"][1]["message"] == "Question annulée."
    assert conversations.totals(loaded) == (2, 3.5, 120)
    assert [c["id"] for c in conversations.list_conversations(tmp_path)] == [conversation["id"]]


def test_list_is_most_recent_first_and_skips_broken_files(tmp_path):
    old, new = conversations.new_conversation(), conversations.new_conversation()
    old["updated"], new["updated"] = "2026-01-01T10:00:00", "2026-11-01T10:00:00"
    conversations.save(old, tmp_path)
    conversations.save(new, tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert [c["id"] for c in conversations.list_conversations(tmp_path)] == [new["id"], old["id"]]
