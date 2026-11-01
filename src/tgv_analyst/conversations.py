"""Saved conversations: one JSON file per conversation in conversations/.

A conversation is a list of questions. Each question keeps its agent events
(events.py) and its summary, so the app can show it again with the same
renderers, without calling the model. Qwen does not remember earlier
questions: every question is still answered on its own.
"""

import json
import uuid
from dataclasses import asdict, fields
from datetime import datetime

from tgv_analyst import events as events_module
from tgv_analyst.config import CONVERSATIONS_DIR

TITLE_LENGTH = 40  # characters of the first question used as the title
EVENT_TYPES = {
    cls.__name__: cls
    for cls in vars(events_module).values()
    if isinstance(cls, type) and hasattr(cls, "__dataclass_fields__")
}


def event_to_dict(event):
    """An event as plain JSON data, with its class name under "type"."""
    return {"type": type(event).__name__, **asdict(event)}


def event_from_dict(data):
    """The event object back from event_to_dict()."""
    cls = EVENT_TYPES[data["type"]]
    return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})


def new_conversation():
    """An empty conversation (saved only once it has a question)."""
    now = datetime.now().isoformat(timespec="seconds")
    return {"id": uuid.uuid4().hex[:12], "title": "", "created": now, "updated": now, "questions": []}


def short_result(result):
    """The part of run_agent's result needed to show the summary line again."""
    trace = result["trace"]
    keep = ("turns", "seconds", "tokens", "unsupported")
    return {"status": result["status"], "trace": {key: trace[key] for key in keep if key in trace}}


def add_question(conversation, question, events, result=None, message=None):
    """Add one finished question. `message` is the text shown instead of a result
    (cancelled, server down...)."""
    if not conversation["title"]:
        title = " ".join(question.split())
        conversation["title"] = title if len(title) <= TITLE_LENGTH else title[: TITLE_LENGTH - 1] + "…"
    conversation["questions"].append({
        "question": question,
        "events": [event_to_dict(event) for event in events],
        "result": short_result(result) if result else None,
        "message": message,
    })
    conversation["updated"] = datetime.now().isoformat(timespec="seconds")


def totals(conversation):
    """(number of questions, seconds, tokens) of a conversation."""
    results = [q["result"]["trace"] for q in conversation["questions"] if q["result"]]
    seconds = sum(trace.get("seconds", 0) for trace in results)
    tokens = sum(trace.get("tokens", 0) for trace in results)
    return len(conversation["questions"]), seconds, tokens


def save(conversation, folder=CONVERSATIONS_DIR):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{conversation['id']}.json"
    path.write_text(json.dumps(conversation, ensure_ascii=False, indent=1), encoding="utf-8")


def load(conversation_id, folder=CONVERSATIONS_DIR):
    return json.loads((folder / f"{conversation_id}.json").read_text(encoding="utf-8"))


def list_conversations(folder=CONVERSATIONS_DIR):
    """Saved conversations, most recent first. Unreadable files are skipped."""
    found = []
    for path in folder.glob("*.json"):
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(found, key=lambda c: c["updated"], reverse=True)
