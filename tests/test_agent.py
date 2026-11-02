"""Tests for agent.py: the loop model -> tools -> guard -> trace (R2, and brick 3 end to end).

Qwen is replaced by FakeModel: llm.chat returns replies written in advance,
in the same format as Ollama, one per turn. Everything else is real: the
loop, the tools (on the 3-row fixture of test_tools.py), the guard and the
trace (written to a temporary file, never to traces/traces.jsonl).

Why a fake model: the spec asks for tests with a known answer that pass on
a fresh clone. Real Qwen answers differently from one run to the next and
needs Ollama running. Checking the real model's answers is brick 9.
The answers below are copied from real Qwen runs of 2026-11-02.
"""

import copy
import json
from pathlib import Path

import pytest

from tgv_analyst import agent, tools
from tgv_analyst.config import PROJECT_ROOT
from tgv_analyst.events import (
    ConfidenceInterval,
    FinalAnswer,
    GuardVerdict,
    Thinking,
    ToolCall,
    ToolResult,
)
from tgv_analyst.prompts import SYSTEM_PROMPT

SMALL_CSV = Path(__file__).parent / "fixtures" / "tgv_small.csv"
QUESTION = "Quel est le taux de retard à l'arrivée de Paris Lyon vers Marseille St Charles en 2024 ?"
# Real Qwen answer. It quotes only numbers that confidence_interval prints: an answer
# that also says "640 trains sur 6704" needs a run_python call that printed them.
CORRECT_ANSWER = (
    "Le taux de retard à l'arrivée des trains TGV Paris Lyon vers Marseille St Charles en 2024 "
    "est de 9,5 %, avec une intervalle de confiance à 95 % allant de 8,9 % à 10,3 %."
)


# --- Fake model ---------------------------------------------------------------

def tool_call(name, arguments, raw=None):
    """A reply where the model asks for one tool. raw: send this text as the arguments instead."""
    return {
        "message": {
            "content": "",
            "tool_calls": [{
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": raw if raw is not None else json.dumps(arguments)},
            }],
        },
        "usage": {"total_tokens": 100},
        "seconds": 0.1,
    }


def answer(text):
    """A reply with text and no tool call: the model's final answer."""
    return {"message": {"content": text}, "usage": {"total_tokens": 50}, "seconds": 0.1}


def empty():
    """A reply with no text and no tool call (seen with thinking on, 2026-11-02)."""
    return answer("")


class FakeModel:
    """Replaces llm.chat: hands back the next written reply and records what it received."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools=None, think=False):
        # deepcopy: the agent keeps adding to the same list after the call
        self.calls.append({"messages": copy.deepcopy(messages), "think": think})
        if not self.replies:
            raise AssertionError("the agent asked the model for more replies than the test wrote")
        return self.replies.pop(0)


@pytest.fixture
def run(monkeypatch, tmp_path):
    """run(replies, ...) answers QUESTION with a fake model. Returns (result, model, trace_file)."""
    monkeypatch.setattr(tools, "CLEAN_CSV", SMALL_CSV)
    trace_file = tmp_path / "traces.jsonl"

    def _run(replies, question=QUESTION, **options):
        model = FakeModel(replies)
        monkeypatch.setattr(agent.llm, "chat", model.chat)
        result = agent.run_agent(question, trace_file=trace_file, **options)
        return result, model, trace_file

    return _run


def tool_messages(model_call):
    """The tool results the model received in one call."""
    return [m for m in model_call["messages"] if m["role"] == "tool"]


# --- Normal path ------------------------------------------------------------------

def test_normal_path(run):
    result, model, trace_file = run([
        tool_call("confidence_interval", {"late": 640, "total": 6704}),
        answer(CORRECT_ANSWER),
    ])
    assert result["status"] == "ok"
    assert result["answer"] == CORRECT_ANSWER
    assert len(model.calls) == 2

    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # one JSON line per question
    trace = json.loads(lines[0])
    assert trace["question"] == QUESTION
    assert trace["status"] == "ok"
    assert trace["turns"] == 2
    assert trace["tokens"] == 150  # 100 + 50
    assert trace["steps"][0]["tool_calls"][0]["result"].startswith("rate: 0.0955 (9.5 %)")


def test_what_the_model_receives(run):
    _, model, _ = run([
        tool_call("confidence_interval", {"late": 640, "total": 6704}),
        answer(CORRECT_ANSWER),
    ])
    first = model.calls[0]["messages"]
    assert first == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": QUESTION},
    ]
    # 2nd call: the tool result comes back, linked to the call that asked for it.
    [tool_message] = tool_messages(model.calls[1])
    assert tool_message["tool_call_id"] == "call_confidence_interval"
    assert tool_message["content"].startswith("rate: 0.0955 (9.5 %)")


def test_with_run_python_on_the_data(run):
    code = (
        "d = df[(df['gare_depart'] == 'PARIS LYON') & (df['year'] == 2024)]\n"
        "print(d['nb_train_retard_arrivee'].sum(), d['nb_circules'].sum())"
    )
    result, model, _ = run([
        tool_call("run_python", {"code": code}),
        tool_call("confidence_interval", {"late": 15, "total": 150}),
        answer("10.0 % des trains étaient en retard (15 sur 150), intervalle de 6.2 % à 15.8 %."),
    ])
    assert result["status"] == "ok"
    assert tool_messages(model.calls[1])[0]["content"].strip() == "15 150"


def test_greeting_needs_no_tool(run):
    result, model, _ = run([answer("Hello! Ask me a question about TGV punctuality.")], question="hello")
    assert result["status"] == "ok"
    assert len(model.calls) == 1


def test_think_setting_reaches_the_model(run):
    _, model, _ = run([answer("Hello!")], question="hello", think=False)
    assert model.calls[0]["think"] is False


# --- Brick 3 end to end: the agent blocks the answer, whatever the model writes ---

def test_invented_number_is_blocked_end_to_end(run):
    """Real Qwen mistake: it wrote 9,55 % (it converted 0.0955 itself), twice."""
    wrong = "Le taux de retard est de **9,55 %**, entre **8,9 % et 10,3 %**."
    result, model, trace_file = run([
        tool_call("confidence_interval", {"late": 640, "total": 6704}),
        answer(wrong),
        answer(wrong),  # same mistake after the second chance
    ])
    assert result["status"] == "rejected"
    assert result["answer"] == "Answer blocked: these numbers were not computed by a tool: 9.55"
    assert "9,55" not in result["answer"]  # the user never sees the wrong answer as an answer

    # The second chance told the model which number was not printed by a tool.
    retry_message = model.calls[2]["messages"][-1]
    assert retry_message["role"] == "user"
    assert "9.55" in retry_message["content"]

    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    assert trace["model_answer"] == wrong  # kept in the trace, to explain the failure
    assert trace["unsupported"] == ["9.55"]


def test_second_chance_can_fix_the_answer(run):
    result, _, _ = run([
        tool_call("confidence_interval", {"late": 640, "total": 6704}),
        answer("Le taux de retard est de **9,6 %**."),  # real Qwen rounding mistake
        answer(CORRECT_ANSWER),
    ])
    assert result["status"] == "ok"
    assert result["answer"] == CORRECT_ANSWER
    assert result["trace"]["retried"] is True


def test_answer_without_any_tool_call_is_blocked(run):
    """The model answers from memory: no tool output, so every number is rejected."""
    result, _, _ = run([answer("Le taux était de 11 %."), answer("Le taux était de 11 %.")])
    assert result["status"] == "rejected"


# --- Edge cases of the loop ---------------------------------------------------------

def test_empty_reply_is_not_an_answer(run):
    """Bug found 2026-11-02: an empty reply was accepted as a final answer (no number to block)."""
    result, model, _ = run([
        tool_call("confidence_interval", {"late": 640, "total": 6704}),
        empty(),
        answer(CORRECT_ANSWER),
    ])
    assert result["status"] == "ok"
    assert result["answer"] == CORRECT_ANSWER
    nudge = model.calls[2]["messages"][-1]
    assert nudge == {"role": "user", "content": "Your reply was empty. Call a tool or write your answer."}


def test_only_empty_replies_never_give_ok(run):
    result, _, _ = run([empty(), empty(), empty()], max_turns=3)
    assert result["status"] == "max_turns"


def test_turn_limit(run):
    """A model that never stops calling tools: the agent stops after max_turns model calls."""
    replies = [tool_call("confidence_interval", {"late": 640, "total": 6704})] * 3
    result, model, _ = run(replies, max_turns=3)
    assert result["status"] == "max_turns"
    assert len(model.calls) == 3
    assert result["answer"] == "The agent did not finish within 3 turns. Try a simpler question."


def test_broken_json_arguments_go_back_to_the_model(run):
    result, model, _ = run([
        tool_call("run_python", None, raw='{"code": "print(len(df))"'),  # missing "}"
        answer("Hello!"),
    ])
    assert result["status"] == "ok"  # no crash, the loop went on
    assert tool_messages(model.calls[1])[0]["content"] == "Error: arguments are not valid JSON."


def test_unknown_tool_goes_back_to_the_model(run):
    _, model, _ = run([tool_call("make_coffee", {}), answer("Hello!")])
    assert tool_messages(model.calls[1])[0]["content"].startswith("Error: unknown tool 'make_coffee'")


def test_forbidden_code_goes_back_to_the_model(run):
    _, model, _ = run([tool_call("run_python", {"code": "df.to_csv('copy.csv')"}), answer("Hello!")])
    assert tool_messages(model.calls[1])[0]["content"].startswith("Error: forbidden in code: to_csv")
    assert not (PROJECT_ROOT / "copy.csv").exists()


# --- Events sent to the display ------------------------------------------------------

def test_events_in_order(run):
    events = []
    run([
        tool_call("confidence_interval", {"late": 640, "total": 6704}),
        answer(CORRECT_ANSWER),
    ], on_event=events.append)
    assert [type(event) for event in events] == [
        Thinking, ToolCall, ToolResult, ConfidenceInterval,  # turn 1: the tool call
        Thinking, GuardVerdict, FinalAnswer,  # turn 2: the answer, checked
    ]
    verdict, final = events[5], events[6]
    assert verdict.passed and verdict.rejected == []
    assert final.sources["9,5"] == 1  # 9,5 % was printed by tool call 1


def test_blocked_answer_events(run):
    events = []
    wrong = "Le taux est de 9,55 %."
    run([tool_call("confidence_interval", {"late": 640, "total": 6704}), answer(wrong), answer(wrong)],
        on_event=events.append)
    verdicts = [event for event in events if isinstance(event, GuardVerdict)]
    assert [(v.passed, v.rejected, v.will_retry) for v in verdicts] == [
        (False, ["9.55"], True),  # first refusal: a second chance follows
        (False, ["9.55"], False),  # second refusal: blocked
    ]
    assert not any(isinstance(event, FinalAnswer) for event in events)


# --- Small helpers -------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"late": 640, "total": 6704}', ({"late": 640, "total": 6704}, None)),
        ({"code": "print(1)"}, ({"code": "print(1)"}, None)),  # some servers send a dict
        ("", ({}, None)),  # edge case: no arguments
        (None, ({}, None)),
        ('{"code": "print(1)"', (None, "Error: arguments are not valid JSON.")),
        ("[1, 2]", (None, "Error: arguments must be a JSON object.")),
    ],
)
def test_parse_arguments(raw, expected):
    assert agent.parse_arguments(raw) == expected


@pytest.mark.parametrize(
    "result, expected",
    [
        ("15 150\n", None),  # it worked
        ("3\n\nError:\nTraceback (most recent call last):\n  File ...\nNameError: name 'x' is not defined\n",
         "NameError: name 'x' is not defined"),
        ("Error: unknown tool 'make_coffee'.", "Error: unknown tool 'make_coffee'."),
    ],
)
def test_error_line(result, expected):
    assert agent.error_line(result) == expected


def test_count_rows():
    assert agent.count_rows(SMALL_CSV) == 3
    assert agent.count_rows(SMALL_CSV.parent / "missing.csv") is None  # edge case: no file


def test_check_startup_all_fine(monkeypatch):
    monkeypatch.setattr(agent.llm, "ping", lambda timeout: 0.02)
    monkeypatch.setattr(agent, "CLEAN_CSV", SMALL_CSV)
    status = agent.check_startup()
    assert status.server_ok and status.data_ok
    assert status.n_rows == 3
    assert status.guard_enabled is True


def test_check_startup_server_down(monkeypatch):
    monkeypatch.setattr(agent.llm, "ping", lambda timeout: None)
    monkeypatch.setattr(agent, "CLEAN_CSV", SMALL_CSV)
    status = agent.check_startup()
    assert status.server_ok is False and status.latency_s is None
    assert status.data_ok is True


def test_check_startup_data_missing(monkeypatch):
    """Fresh clone before scripts/download_data.py and clean_data.py were run."""
    monkeypatch.setattr(agent.llm, "ping", lambda timeout: 0.02)
    monkeypatch.setattr(agent, "CLEAN_CSV", SMALL_CSV.parent / "missing.csv")
    status = agent.check_startup()
    assert status.data_ok is False and status.n_rows is None


def test_sources_prefer_the_most_recent_tool_call():
    """Real case of 2026-11-02: "12.0 %" came from confidence_interval (call 3), but
    describe_dataset (call 1) prints "month number (1-12)" and 12 rounds to 12.0."""
    outputs = {
        1: "Columns:\n- month: month number (1-12)",
        2: "Late trains: 1385\nTotal trains that ran: 11554",
        3: "rate: 0.1199 (12.0 %)\n95% confidence interval: [0.1141, 0.1259] ([11.4 %, 12.6 %])",
    }
    answer = "In 2023, 12.0 % arrived late, between 11.4 % and 12.6 % (1,385 out of 11,554)."
    sources = agent.find_sources(answer, "late share in 2023?", outputs)
    assert sources == {"12.0": 3, "11.4": 3, "12.6": 3, "1,385": 2, "11,554": 2}
