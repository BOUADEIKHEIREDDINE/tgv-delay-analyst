"""The agent loop: question -> model -> tools -> ... -> checked answer.

llm.py talks to the model, tools.py runs the tools, guard.py checks the
answer. This file connects them and saves a trace of every question.
"""

import json
import time
from datetime import datetime

from tgv_analyst import llm
from tgv_analyst.config import CLEAN_CSV, PING_TIMEOUT_S, PROJECT_ROOT
from tgv_analyst.events import (
    ConfidenceInterval,
    FinalAnswer,
    GuardVerdict,
    Reasoning,
    StartupStatus,
    Thinking,
    ToolCall,
    ToolResult,
)
from tgv_analyst.guard import NUMBER_PATTERN, check_answer, extract_numbers, is_supported
from tgv_analyst.prompts import DATA_FACTS, SYSTEM_PROMPT
from tgv_analyst.stats import confidence_interval as wilson_interval
from tgv_analyst.tools import TOOL_SCHEMAS, call_tool

MAX_TURNS = 10  # model calls per question, including the retry after a rejection
TRACE_FILE = PROJECT_ROOT / "traces" / "traces.jsonl"
GUARD_ENABLED = True  # the guard always runs: there is no option to turn it off


def parse_arguments(raw):
    """Decode the tool arguments sent by the model (a JSON string).

    Returns (arguments, error). Broken JSON gives an error message for the
    model instead of a crash.
    """
    if isinstance(raw, dict):  # some servers already send a dict
        return raw, None
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None, "Error: arguments are not valid JSON."
    if not isinstance(arguments, dict):
        return None, "Error: arguments must be a JSON object."
    return arguments, None


def count_rows(path):
    """Number of data rows in a CSV file (header excluded), or None if unreadable."""
    try:
        with open(path, encoding="utf-8") as file:
            return sum(1 for _ in file) - 1
    except OSError:
        return None


def check_startup():
    """Check that the model server answers and the clean data is there."""
    latency = llm.ping(PING_TIMEOUT_S)
    n_rows = count_rows(CLEAN_CSV)
    return StartupStatus(
        server_ok=latency is not None,
        latency_s=latency,
        data_ok=n_rows is not None and n_rows > 0,
        n_rows=n_rows,
        model_name=llm.MODEL,
        endpoint=llm.endpoint(),
        guard_enabled=GUARD_ENABLED,
    )


def emit(on_event, event):
    """Send a progress event (events.py) to the display, if there is one."""
    if on_event:
        on_event(event)


def error_line(result):
    """The last line of a failed tool result (e.g. "NameError: ..."), or None if it worked."""
    if not (result.startswith("Error") or "Traceback (most recent call last)" in result):
        return None
    lines = [line for line in result.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "Error"


def call_text(name, arguments):
    """What ToolCall shows: the code for run_python, the arguments for the other tools."""
    if name == "run_python" and arguments and "code" in arguments:
        return arguments["code"]
    return json.dumps(arguments, ensure_ascii=False) if arguments else ""


def interval_event(arguments):
    """The ConfidenceInterval event for a confidence_interval call (same function as the tool)."""
    late, total = arguments["late"], arguments["total"]
    rate, low, high = wilson_interval(late, total)
    return ConfidenceInterval(label=f"{late} / {total}", estimate=rate, low=low, high=high)


def find_sources(answer, question, outputs):
    """For each number written in the answer, the first tool call that printed it.

    outputs: {call_id: tool output}. Numbers that come from the question get no source.
    Uses the same rounding rule as the guard, so a source exists for every accepted number.
    """
    from_question = extract_numbers(question)
    sources = {}
    for written in NUMBER_PATTERN.findall(answer):
        number = extract_numbers(written)[0]
        if is_supported(number, from_question):
            continue
        for call_id, output in outputs.items():
            if is_supported(number, extract_numbers(output)):
                sources[written] = call_id
                break
    return sources


def save_trace(trace, trace_file):
    """Append one question's trace as one JSON line."""
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    with open(trace_file, "a", encoding="utf-8") as file:
        file.write(json.dumps(trace, ensure_ascii=False) + "\n")


def run_agent(question, think=True, max_turns=MAX_TURNS, trace_file=TRACE_FILE, on_event=None):
    """Answer a question with the model and the tools.

    on_event: optional function called with an event (events.py) at each
    step, so the CLI can show progress. The benchmark does not pass it.

    Returns a dict:
        answer: the text to show the user
        status: "ok", "rejected" (guard refused twice) or "max_turns"
        trace:  everything that happened (also saved in trace_file)
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_outputs = []  # exact text returned by the tools: what the guard checks against
    outputs_by_call = {}  # call_id -> output, to show where each number comes from
    steps = []
    tokens = 0
    retried = False
    model_answer = None
    unsupported = []
    status = "max_turns"
    start = time.time()

    for turn in range(1, max_turns + 1):
        emit(on_event, Thinking(step=turn))
        reply = llm.chat(messages, tools=TOOL_SCHEMAS, think=think)
        message = reply["message"]
        tokens += reply["usage"].get("total_tokens", 0)
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""

        # Keep only the fields the API expects back (not the reasoning text).
        assistant_message = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)

        step = {"turn": turn, "seconds": reply["seconds"], "content": content}
        reasoning = message.get("reasoning") or message.get("reasoning_content")
        if reasoning:
            step["reasoning"] = reasoning  # saved in the trace, shown only with --show-thinking
            emit(on_event, Reasoning(step=turn, text=reasoning))

        if tool_calls:
            step["tool_calls"] = []
            for call in tool_calls:
                name = call["function"]["name"]
                arguments, error = parse_arguments(call["function"].get("arguments"))
                call_id = len(outputs_by_call) + 1
                emit(on_event, ToolCall(call_id=call_id, code=call_text(name, arguments), name=name))
                tool_start = time.time()
                result = error if error else call_tool(name, arguments)
                result = str(result)
                tool_seconds = round(time.time() - tool_start, 2)
                outputs_by_call[call_id] = result
                failed = error_line(result)
                emit(on_event, ToolResult(
                    call_id=call_id,
                    output=result,
                    numbers=[float(n) for n in extract_numbers(result)],
                    error=failed,
                ))
                if name == "confidence_interval" and not failed:
                    emit(on_event, interval_event(arguments))
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
                tool_outputs.append(result)
                step["tool_calls"].append({
                    "name": name,
                    "arguments": arguments if arguments is not None else call["function"].get("arguments"),
                    "result": result,
                    "seconds": tool_seconds,
                })
            steps.append(step)
            continue

        if not content.strip():
            # With thinking on, the model sometimes stops with an empty reply: ask it to go on.
            steps.append(step)
            messages.append({"role": "user", "content": "Your reply was empty. Call a tool or write your answer."})
            continue

        # No tool call: this is the model's final answer. Brick 3: check it in code.
        steps.append(step)
        model_answer = content
        # Numbers from the question and from the data description are not made up.
        ok, unsupported = check_answer(model_answer, tool_outputs, f"{DATA_FACTS}\n{question}")
        step["guard"] = {"ok": ok, "unsupported": unsupported}
        emit(on_event, GuardVerdict(
            passed=ok,
            checked=extract_numbers(model_answer),
            rejected=unsupported,
            will_retry=not ok and not retried,
        ))
        if ok:
            status = "ok"
            emit(on_event, FinalAnswer(
                text=model_answer,
                sources=find_sources(model_answer, f"{DATA_FACTS}\n{question}", outputs_by_call),
            ))
            break
        if retried:
            status = "rejected"
            break
        # One second chance: tell the model which numbers no tool printed.
        retried = True
        messages.append({
            "role": "user",
            "content": (
                "These numbers in your answer were not printed by any tool: "
                f"{', '.join(unsupported)}. Compute them with run_python, "
                "or remove them, then answer again."
            ),
        })

    if status == "ok":
        answer = model_answer
    elif status == "rejected":
        answer = (
            "Answer blocked: these numbers were not computed by a tool: "
            f"{', '.join(unsupported)}"
        )
    else:
        answer = f"The agent did not finish within {max_turns} turns. Try a simpler question."

    trace = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": llm.MODEL,
        "think": think,
        "question": question,
        "status": status,
        "answer": answer,
        "model_answer": model_answer,  # last answer the model wrote, even if blocked
        "unsupported": unsupported,
        "retried": retried,
        "turns": len(steps),
        "tokens": tokens,
        "seconds": round(time.time() - start, 2),
        "steps": steps,
    }
    save_trace(trace, trace_file)
    return {"answer": answer, "status": status, "trace": trace}
