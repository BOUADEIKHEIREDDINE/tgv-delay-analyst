"""Tests for llm.py: how the request to the model server is built and the reply read (R2).

No server is needed: urllib.request.urlopen (the function that sends the HTTP
request) is replaced by a fake that records the request and returns a reply
written in the test, in the format Ollama sends.
"""

import importlib
import io
import json
import urllib.error

import pytest

from tgv_analyst import llm

OLLAMA_REPLY = {  # shape of a real Ollama /chat/completions reply
    "choices": [{"message": {"role": "assistant", "content": "Hello! How are you?"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17},
}


class FakeResponse(io.BytesIO):
    """What urlopen returns: a readable body, usable in a `with` block (BytesIO already is)."""


@pytest.fixture
def server(monkeypatch):
    """Replace urlopen. server.requests lists every request sent; server.reply is what comes back."""

    class Server:
        requests = []
        reply = OLLAMA_REPLY
        error = None  # an exception to raise instead of replying

        @classmethod
        def urlopen(cls, request, timeout):
            cls.requests.append({"request": request, "timeout": timeout})
            if cls.error:
                raise cls.error
            return FakeResponse(json.dumps(cls.reply).encode("utf-8"))

    Server.requests = []
    monkeypatch.setattr(llm.urllib.request, "urlopen", Server.urlopen)
    monkeypatch.setattr(llm, "BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(llm, "MODEL", "qwen3.5-4b-16k")
    monkeypatch.setattr(llm, "API_KEY", "")
    return Server


def sent_body(server):
    """The JSON body of the last request, as a dict."""
    return json.loads(server.requests[-1]["request"].data)


# --- chat: the request ------------------------------------------------------------

def test_chat_sends_the_conversation_to_the_chat_endpoint(server):
    messages = [{"role": "user", "content": "hello"}]
    llm.chat(messages)
    request = server.requests[-1]["request"]
    assert request.full_url == "http://localhost:11434/v1/chat/completions"
    assert request.get_method() == "POST"  # a request with a body is a POST
    assert request.get_header("Content-type") == "application/json"
    assert sent_body(server) == {
        "model": "qwen3.5-4b-16k",
        "messages": messages,
        "reasoning_effort": "none",  # think=False by default
    }


def test_chat_think_true_keeps_the_reasoning_on(server):
    llm.chat([{"role": "user", "content": "hello"}], think=True)
    assert "reasoning_effort" not in sent_body(server)


def test_chat_sends_the_tools_only_when_given(server):
    tools = [{"type": "function", "function": {"name": "describe_dataset"}}]
    llm.chat([{"role": "user", "content": "hi"}], tools=tools)
    assert sent_body(server)["tools"] == tools
    llm.chat([{"role": "user", "content": "hi"}], tools=None)
    assert "tools" not in sent_body(server)


def test_chat_sends_no_key_by_default(server):
    """Local Ollama needs no key: no Authorization header at all."""
    llm.chat([{"role": "user", "content": "hi"}])
    assert server.requests[-1]["request"].get_header("Authorization") is None


def test_chat_sends_the_key_when_set(server, monkeypatch):
    """Cerebras fallback: the key comes from LLM_API_KEY, never from the code."""
    monkeypatch.setattr(llm, "API_KEY", "test-key")
    llm.chat([{"role": "user", "content": "hi"}])
    assert server.requests[-1]["request"].get_header("Authorization") == "Bearer test-key"


def test_chat_uses_the_long_timeout(server):
    llm.chat([{"role": "user", "content": "hi"}])
    assert server.requests[-1]["timeout"] == llm.TIMEOUT_SECONDS == 600


# --- chat: the reply ----------------------------------------------------------------

def test_chat_returns_message_usage_and_seconds(server):
    result = llm.chat([{"role": "user", "content": "hello"}])
    assert result["message"] == {"role": "assistant", "content": "Hello! How are you?"}
    assert result["usage"]["total_tokens"] == 17
    assert isinstance(result["seconds"], float) and result["seconds"] >= 0


def test_chat_returns_tool_calls(server):
    tool_call = {"id": "call_1", "type": "function",
                 "function": {"name": "run_python", "arguments": '{"code": "print(len(df))"}'}}
    server.reply = {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [tool_call]}}]}
    result = llm.chat([{"role": "user", "content": "how many rows?"}])
    assert result["message"]["tool_calls"] == [tool_call]


def test_chat_reply_without_usage(server):
    """Edge case: some servers send no token counts -> empty dict, not a crash."""
    server.reply = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    assert llm.chat([{"role": "user", "content": "hi"}])["usage"] == {}


# --- chat: errors -------------------------------------------------------------------

def test_chat_no_server_gives_a_clear_error(server):
    server.error = urllib.error.URLError("Connection refused")
    with pytest.raises(ConnectionError, match=r"Is Ollama running\? \(ollama serve\)"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_server_error_shows_the_server_message(server):
    """Real case of 2026-11-01: wrong model name -> 404 with Ollama's message."""
    body = io.BytesIO(b'{"error":"model \'nope\' not found"}')
    server.error = urllib.error.HTTPError("http://localhost:11434/v1/chat/completions", 404, "Not Found", {}, body)
    with pytest.raises(RuntimeError, match=r"Model server error 404: .*model 'nope' not found"):
        llm.chat([{"role": "user", "content": "hi"}])


# --- ping and endpoint ----------------------------------------------------------------

def test_ping_returns_the_time(server):
    seconds = llm.ping(timeout=5)
    assert isinstance(seconds, float) and seconds >= 0
    request = server.requests[-1]
    assert request["request"].full_url == "http://localhost:11434/v1/models"
    assert request["timeout"] == 5


@pytest.mark.parametrize("error", [urllib.error.URLError("refused"), TimeoutError(), OSError("network down")])
def test_ping_returns_none_when_the_server_does_not_answer(server, error):
    server.error = error
    assert llm.ping(timeout=1) is None


def test_endpoint_is_host_and_port_only(monkeypatch):
    """Shown in the startup banner: never the path, never a key."""
    monkeypatch.setattr(llm, "BASE_URL", "http://localhost:11434/v1")
    assert llm.endpoint() == "localhost:11434"
    monkeypatch.setattr(llm, "BASE_URL", "https://api.cerebras.ai/v1")
    assert llm.endpoint() == "api.cerebras.ai"


# --- settings from environment variables ------------------------------------------------

def test_settings_default_and_from_environment(monkeypatch):
    """Defaults work with no setup (fresh clone); LLM_* variables override them."""
    for name in ["LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    try:
        importlib.reload(llm)  # the settings are read when the module is imported
        assert (llm.BASE_URL, llm.MODEL, llm.API_KEY) == ("http://localhost:11434/v1", "qwen3.5-4b-16k", "")

        monkeypatch.setenv("LLM_BASE_URL", "https://api.cerebras.ai/v1")
        monkeypatch.setenv("LLM_MODEL", "qwen-3.8-27b")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        importlib.reload(llm)
        assert (llm.BASE_URL, llm.MODEL, llm.API_KEY) == ("https://api.cerebras.ai/v1", "qwen-3.8-27b", "test-key")
    finally:
        monkeypatch.undo()  # put the environment back...
        importlib.reload(llm)  # ...and the module settings with it
