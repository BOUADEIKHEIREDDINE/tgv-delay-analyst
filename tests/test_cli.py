"""Tests for cli.py: the `tgv` command, its options and the line-by-line mode (R2).

The display, the agent and the startup check are replaced by fakes: these
tests check what cli.py decides (which function is called, with which
setting, what happens on an error), not how things are drawn (test_ui.py)
or answered (test_agent.py).
"""

from contextlib import contextmanager

import pytest

from tgv_analyst import cli, ui
from tgv_analyst.events import StartupStatus

ALL_FINE = StartupStatus(True, 0.02, True, 12792, "qwen-test", "localhost:11434", True)
SERVER_DOWN = StartupStatus(False, None, True, 12792, "qwen-test", "localhost:11434", True)
RESULT = {"status": "ok", "answer": "There are 12792 rows.", "trace": {}}


class FakeDisplay:
    """Records every call cli.py makes, as (method name, arguments)."""

    def __init__(self, lines=(), **options):
        self.options = options  # what ui.Display(...) was created with
        self.lines = list(lines)  # what the user "types", then Ctrl-D
        self.calls = []

    def read_question(self):
        if not self.lines:
            raise EOFError  # Ctrl-D
        line = self.lines.pop(0)
        if isinstance(line, BaseException):
            raise line
        return line

    @contextmanager
    def checking(self):
        self.calls.append(("checking",))
        yield

    def names(self):
        return [call[0] for call in self.calls]

    def errors(self):
        return [call[1] for call in self.calls if call[0] == "show_error"]

    def __getattr__(self, name):
        # Any other display method (show_result, show_help, ...) just records its call.
        return lambda *args: self.calls.append((name, *args))


@pytest.fixture
def fake_agent(monkeypatch):
    """Replaces run_agent. agent.questions lists (question, think); agent.error is raised if set."""

    class Agent:
        questions = []
        error = None

        @classmethod
        def run(cls, question, think, on_event):
            cls.questions.append((question, think))
            if cls.error:
                raise cls.error
            return RESULT

    Agent.questions = []
    monkeypatch.setattr(cli, "run_agent", Agent.run)
    monkeypatch.setattr(cli, "check_startup", lambda: ALL_FINE)
    return Agent


# --- ask: one question --------------------------------------------------------------

def test_ask_shows_the_result(fake_agent):
    display = FakeDisplay()
    cli.ask(display, "How many rows?", think=True)
    assert fake_agent.questions == [("How many rows?", True)]
    assert display.names() == ["start_question", "stop_spinner", "show_result"]
    assert display.calls[-1] == ("show_result", RESULT)


def test_ask_server_down_gives_the_fix_command(fake_agent):
    fake_agent.error = ConnectionError("not reachable")
    display = FakeDisplay()
    cli.ask(display, "How many rows?", think=True)
    assert display.errors() == ["The model server does not answer. Run: ollama serve"]
    assert "stop_spinner" in display.names()  # the spinner stops even after an error
    assert "show_result" not in display.names()


def test_ask_server_error_shows_its_message(fake_agent):
    fake_agent.error = RuntimeError("Model server error 404: model 'nope' not found")
    display = FakeDisplay()
    cli.ask(display, "How many rows?", think=True)
    assert display.errors() == ["Model server error 404: model 'nope' not found"]


# --- /commands ------------------------------------------------------------------------

def test_command_help():
    display = FakeDisplay()
    cli.run_command(display, "/help")
    assert display.names() == ["show_help"]


def test_command_trace():
    display = FakeDisplay()
    cli.run_command(display, "/trace")
    assert display.names() == ["show_trace"]


def test_command_log(monkeypatch):
    rows = [["step", "rule", "rows_affected"], ["remove_impossible_rows", "...", "73"]]
    monkeypatch.setattr(cli, "read_cleaning_log", lambda: rows)
    display = FakeDisplay()
    cli.run_command(display, "/log")
    assert display.calls == [("show_log", rows)]


def test_command_log_without_the_file(monkeypatch):
    """Edge case: fresh clone before the data scripts were run."""
    monkeypatch.setattr(cli, "read_cleaning_log", lambda: None)
    display = FakeDisplay()
    cli.run_command(display, "/log")
    assert display.errors() == [f"No cleaning log. Run: {ui.DATA_FIX_COMMAND}"]


def test_command_status(fake_agent):
    display = FakeDisplay()
    cli.run_command(display, "/status")
    assert display.calls == [("checking",), ("show_status", ALL_FINE)]


def test_unknown_command():
    display = FakeDisplay()
    cli.run_command(display, "/coffee")
    assert display.errors() == ["Unknown command: /coffee. Type /help."]


# --- repl: the line-by-line mode ------------------------------------------------------

def test_repl_routes_questions_and_commands(fake_agent):
    display = FakeDisplay(lines=["How many rows?", "", "   ", "/HELP", "Which route?"])
    cli.repl(display, think=False)
    assert fake_agent.questions == [("How many rows?", False), ("Which route?", False)]  # blank lines skipped
    assert "show_help" in display.names()  # commands are not case-sensitive


@pytest.mark.parametrize("word", ["/quit", "/exit", "quit", "EXIT"])
def test_repl_quit_words(fake_agent, word):
    display = FakeDisplay(lines=[word, "never asked"])
    cli.repl(display, think=True)
    assert fake_agent.questions == []


@pytest.mark.parametrize("key", [EOFError(), KeyboardInterrupt()])
def test_repl_ctrl_d_or_ctrl_c_at_the_prompt_quits(fake_agent, key):
    display = FakeDisplay(lines=[key, "never asked"])
    cli.repl(display, think=True)
    assert fake_agent.questions == []


def test_repl_ctrl_c_during_a_question_cancels_it_and_goes_on(fake_agent):
    fake_agent.error = KeyboardInterrupt()
    display = FakeDisplay(lines=["Slow question", "/help"])
    cli.repl(display, think=True)
    assert "Question cancelled." in display.errors()
    assert "show_help" in display.names()  # the REPL kept going


# --- main: the options --------------------------------------------------------------------

@pytest.fixture
def command(monkeypatch, fake_agent):
    """command("tgv", "--no-think", ...) runs main() with these arguments. Returns (exit code, display)."""
    created = []

    def fake_display(**options):
        created.append(FakeDisplay(**options))
        return created[-1]

    monkeypatch.setattr(cli.ui, "Display", fake_display)

    def _command(*argv, tty=False):
        monkeypatch.setattr(cli.sys, "argv", list(argv))
        monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: tty)
        code = cli.main()
        return code, created[-1]

    return _command


def test_one_question(command, fake_agent):
    """Bug found 2026-11-02: this crashed with AttributeError (ui.Arrival.SUPPRIME, renamed CANCELLED)."""
    code, display = command("tgv", "How many rows?")
    assert code == 0
    assert fake_agent.questions == [("How many rows?", True)]  # thinking on by default
    assert display.names()[:2] == ["checking", "show_startup"]  # startup banner first


def test_no_think_option(command, fake_agent):
    command("tgv", "--no-think", "How many rows?")
    assert fake_agent.questions == [("How many rows?", False)]


def test_one_question_server_down_exits_with_1(command, fake_agent, monkeypatch):
    """The banner shows the fix; no question is sent to a server that isn't there."""
    monkeypatch.setattr(cli, "check_startup", lambda: SERVER_DOWN)
    code, _ = command("tgv", "How many rows?")
    assert code == 1
    assert fake_agent.questions == []


def test_display_options(command):
    _, display = command("tgv", "--plain", "--no-anim", "--show-thinking", "How many rows?")
    assert display.options == {"plain": True, "animate": False, "show_thinking": True}


@pytest.mark.parametrize("option", ["--simple", "--plain"])
def test_simple_and_plain_use_the_line_by_line_mode(command, monkeypatch, option):
    monkeypatch.setattr(cli, "TgvApp", lambda **kwargs: pytest.fail("the full-screen app should not start"))
    code, display = command("tgv", option, tty=True)
    assert code == 0
    assert display.names()[-1] == "show_goodbye"  # the REPL ended at Ctrl-D (no lines typed)


def test_no_terminal_uses_the_line_by_line_mode(command, monkeypatch):
    """Output redirected to a file or a pipe: no full-screen app."""
    monkeypatch.setattr(cli, "TgvApp", lambda **kwargs: pytest.fail("the full-screen app should not start"))
    code, _ = command("tgv", tty=False)
    assert code == 0


def test_no_question_in_a_terminal_starts_the_full_screen_app(command, monkeypatch):
    started = []

    class FakeApp:
        def __init__(self, **options):
            started.append(options)

        def run(self):
            started.append("run")

    monkeypatch.setattr(cli, "TgvApp", FakeApp)
    code, _ = command("tgv", "--no-think", tty=True)
    assert code == 0
    assert started == [{"think": False, "show_thinking": False, "animate": True}, "run"]
