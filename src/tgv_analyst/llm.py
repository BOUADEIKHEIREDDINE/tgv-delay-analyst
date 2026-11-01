"""Talk to the model: send the conversation, get the reply back.

The model runs in Ollama, a local server with an OpenAI-compatible API.
This file does not run tools or loop: that is agent.py's job.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# Settings come from environment variables (see .env.example), with defaults for Ollama.
BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen3.5-4b-16k")
API_KEY = os.environ.get("LLM_API_KEY", "")  # only needed for the Cerebras fallback
TIMEOUT_SECONDS = 600  # thinking mode can be slow on a laptop


def chat(messages, tools=None, think=False):
    """Send one request to the model and return its reply.

    messages: the conversation, e.g. [{"role": "user", "content": "..."}]
    tools: the tool schemas the model may call (TOOL_SCHEMAS in tools.py)
    think: False turns off the model's reasoning (much faster)

    Returns a dict:
        message: the reply (keys "content", and "tool_calls" if it calls tools)
        usage:   token counts (prompt_tokens, completion_tokens, total_tokens)
        seconds: how long the request took
    """
    body = {"model": MODEL, "messages": messages}
    if tools:
        body["tools"] = tools
    if not think:
        body["reasoning_effort"] = "none"

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )

    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        # The server answered with an error (wrong model name, bad request...).
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model server error {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        # No server at that address.
        raise ConnectionError(
            f"Model server not reachable at {BASE_URL}. Is Ollama running? (ollama serve)"
        ) from error

    return {
        "message": data["choices"][0]["message"],
        "usage": data.get("usage", {}),
        "seconds": round(time.time() - start, 2),
    }


def endpoint():
    """Host and port of the model server, e.g. "localhost:11434" (never the key)."""
    return urllib.parse.urlparse(BASE_URL).netloc


def ping(timeout):
    """Time in seconds for a tiny request to the server (list of models).

    Returns None if the server does not answer within `timeout` seconds.
    """
    request = urllib.request.Request(f"{BASE_URL}/models")
    if API_KEY:
        request.add_header("Authorization", f"Bearer {API_KEY}")
    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return round(time.time() - start, 3)
