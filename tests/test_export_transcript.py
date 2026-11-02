"""Tests for ai_log/export_transcript.py (R3 tool): what is kept, what is removed."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "ai_log" / "export_transcript.py"
spec = importlib.util.spec_from_file_location("export_transcript", SCRIPT)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def test_clean_removes_reminders_and_personal_data():
    text = "hi <system-reminder>secret memory</system-reminder> mail me: someone@example.com, /home/alice/x"
    assert export.clean(text) == "hi  mail me: [email], ~/x"


def test_shorten():
    assert export.shorten("abc", 5) == "abc"
    assert export.shorten("abcdefgh", 3) == "abc\n… (5 more characters)"


def test_to_markdown(tmp_path):
    records = [
        {"type": "user", "timestamp": "2026-11-02T10:00:00Z", "message": {"content": "How many rows?"}},
        {"type": "user", "isMeta": True, "message": {"content": "hidden meta message"}},
        {"type": "assistant", "timestamp": "2026-11-02T10:00:05Z", "message": {"content": [
            {"type": "thinking", "thinking": "private reasoning"},
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "wc -l data.csv"}},
        ]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "12793 data.csv"}]}},
        "not json",
    ]
    session = tmp_path / "s.jsonl"
    session.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in records), encoding="utf-8")
    text = export.to_markdown(session, "Test session")
    assert text.startswith("# Test session")
    assert "## User · 2026-11-02 10:00" in text and "How many rows?" in text
    assert "## Claude · 2026-11-02 10:00" in text and "Let me check." in text
    assert "$ wc -l data.csv" in text and "12793 data.csv" in text
    assert "hidden meta message" not in text and "private reasoning" not in text
