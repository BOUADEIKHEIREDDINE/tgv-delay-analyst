"""Turn a Claude Code session file (.jsonl) into a readable Markdown export for ai_log/ (R3).

    python ai_log/export_transcript.py SESSION.jsonl ai_log/conversations/2026-11-01-afternoon-full.md

Kept in full: the user's messages and the assistant's replies. Each tool call is shown
with its input; tool outputs are shortened. Removed: hidden system reminders and the
model's private reasoning (not shown in the conversation). Personal data: the e-mail
address and the home folder are replaced.
"""

import json
import re
import sys
from pathlib import Path

MAX_TOOL_INPUT = 3000
MAX_TOOL_OUTPUT = 1500
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|bouadikheireddine@?")  # also the address's name part
HOME = re.compile(r"/home/[\w.-]+")


def clean(text):
    """Remove hidden reminders and personal data."""
    text = REMINDER.sub("", text)
    text = EMAIL.sub("[email]", text)
    text = HOME.sub("~", text)
    return text.strip()


def shorten(text, limit):
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more characters)"


def tool_input_text(block):
    data = block.get("input", {})
    if block.get("name") == "Bash":
        return f"$ {data.get('command', '')}"
    if block.get("name") in ("Write", "Edit"):
        return json.dumps({k: v for k, v in data.items()}, ensure_ascii=False, indent=1)
    return json.dumps(data, ensure_ascii=False)


def result_text(content):
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))


def entries(path):
    """(time, role, markdown) for each visible part of the session, in order."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") not in ("user", "assistant") or record.get("isMeta"):
            continue
        time = (record.get("timestamp") or "")[:16].replace("T", " ")
        content = record.get("message", {}).get("content")
        if isinstance(content, str):
            text = clean(content)
            if text and not text.startswith("<command-") and not text.startswith("<local-command"):
                yield time, record["type"], text
            continue
        for block in content or []:
            kind = block.get("type")
            if kind == "text" and clean(block.get("text", "")):
                yield time, record["type"], clean(block["text"])
            elif kind == "tool_use":
                text = clean(shorten(tool_input_text(block), MAX_TOOL_INPUT))
                yield time, "tool", f"**Tool · {block.get('name')}**\n\n```\n{text}\n```"
            elif kind == "tool_result":
                text = clean(shorten(result_text(block.get("content", "")), MAX_TOOL_OUTPUT))
                if text:
                    yield time, "result", f"```\n{text}\n```"


def to_markdown(path, title):
    lines = [f"# {title}", "", f"Full export of a Claude Code session (`{Path(path).name}`).", ""]
    names = {"user": "User", "assistant": "Claude"}
    for time, role, text in entries(path):
        if role in names:
            lines += [f"## {names[role]} · {time}", "", text, ""]
        else:
            lines += [text, ""]
    return "\n".join(lines)


if __name__ == "__main__":
    source, target = sys.argv[1], Path(sys.argv[2])
    title = sys.argv[3] if len(sys.argv) > 3 else target.stem
    target.write_text(to_markdown(source, title), encoding="utf-8")
    print(f"Saved {target}")
