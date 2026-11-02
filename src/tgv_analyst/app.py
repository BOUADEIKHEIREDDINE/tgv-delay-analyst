"""The interactive full-screen app (Textual), like the Claude Code CLI.

Layout, from top to bottom:
- the history: banner, questions, tool calls, answers; it scrolls with the
  mouse wheel or two fingers on a touchpad, and follows new content;
- a status line: the thinking spinner while Qwen works;
- the question box, always at the bottom: multi-line, mouse selection,
  delete a selection, \\ + Enter for a new line;
- a hint line, then the data limits (brick 8, like "Claude can make mistakes");
- on the right, the panel (sidebar.py): session, conversations, starters.

Conversations are saved in conversations/ (conversations.py) and can be
reopened from the panel. Qwen does not remember earlier questions.

Like cli.py, this file connects the agent and the display: it calls
check_startup() and run_agent(), and draws their events with the renderers
of ui.py (the same ones as the simple display). All colors come from theme.py.
"""

import csv
import threading
import time

from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static, TextArea

from tgv_analyst import conversations, theme, ui
from tgv_analyst.agent import check_startup, run_agent
from tgv_analyst.config import CLEANING_LOG, CONVERSATIONS_DIR
from tgv_analyst.events import FinalAnswer, Reasoning, Thinking
from tgv_analyst.sidebar import Sidebar

QUIT_COMMANDS = {"/quit", "/exit"}
NEW_LINE_KEYS = {"shift+enter", "alt+enter", "ctrl+j"}  # sent by some terminals instead of \ + Enter
HINT = "enter send · \\ + enter new line · esc cancel · /help · /quit"
PLACEHOLDER = "Ask a question about TGV punctuality…"
SIDEBAR_WIDTH = 38
SIDEBAR_MIN_SCREEN = 100  # narrower terminal: the panel starts hidden (Ctrl+B shows it)


class QuestionCancelled(Exception):
    """Raised inside an abandoned agent thread, to stop it at its next event."""


def read_cleaning_log():
    """Rows of data/cleaning_log.csv (header first), or None if the file is missing."""
    try:
        with open(CLEANING_LOG, encoding="utf-8", newline="") as file:
            return list(csv.reader(file))
    except OSError:
        return None


def user_line(question):
    """How a question appears in the history: "› question", on several lines if needed."""
    return Text.assemble((ui.PROMPT_MARK, f"bold {theme.ACCENT}"), question)


class QuestionBox(TextArea):
    """The question box: Enter sends, \\ + Enter (or Shift+Enter) adds a new line.

    Everything else (mouse selection, Shift+arrows, deleting a selection,
    Ctrl+Z) is standard TextArea behavior.
    """

    class Submitted(Message):
        """The user pressed Enter: `text` is the whole question."""

        def __init__(self, text):
            super().__init__()
            self.text = text

    async def _on_key(self, event):
        if event.key in NEW_LINE_KEYS:
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            row, column = self.cursor_location
            if column > 0 and self.document.get_line(row)[column - 1] == ui.NEW_LINE_KEY:
                self.replace("\n", (row, column - 1), (row, column))  # the \ becomes a new line
            else:
                self.post_message(self.Submitted(self.text))
            return
        await super()._on_key(event)

    def action_paste(self):
        """Ctrl+V pastes the app's own clipboard (text copied inside the app). The system
        clipboard can't be read by a terminal app: the terminal sends it on ctrl+shift+v."""
        if self.app.clipboard:
            super().action_paste()
        else:
            self.app.notify(ui.PASTE_TIP, timeout=4)


class TgvApp(App):
    """Full-screen app. `startup` and `agent` can be replaced in tests (no model needed)."""

    CSS = f"""
    Screen {{ background: ansi_default; }}
    #main {{ width: 1fr; }}
    Sidebar {{
        width: {SIDEBAR_WIDTH}; padding: 1 1 0 2; background: ansi_default;
        border-left: solid {theme.MUTED}; scrollbar-size-vertical: 1;
    }}
    Sidebar.-hidden {{ display: none; }}
    Sidebar .section {{ margin-top: 1; }}
    Sidebar OptionList {{ height: auto; max-height: 14; border: none; padding: 0; background: ansi_default; }}
    Sidebar OptionList:focus {{ border: none; }}
    Sidebar OptionList > .option-list--option-highlighted {{
        background: ansi_default; color: {theme.ACCENT}; text-style: bold;
    }}
    Sidebar OptionList > .option-list--option-hover {{ background: ansi_default; text-style: underline; }}
    #history {{ height: 1fr; padding: 0 1; scrollbar-size-vertical: 1; }}
    #history > Static {{ margin-bottom: 1; }}
    #history > #banner {{ margin: {ui.TOP_MARGIN} 0 1 0; }}  /* more specific than the rule above */
    #status {{ height: auto; padding: 0 2; }}
    QuestionBox {{
        height: auto; max-height: 12; min-height: 3;
        background: ansi_default; border: round {theme.MUTED}; padding: 0 1;
    }}
    QuestionBox:focus {{ border: round {theme.ACCENT}; }}
    #hint {{ height: 1; padding: 0 2; color: {theme.MUTED}; }}
    #limits {{ height: auto; padding: 0 2; color: {theme.MUTED}; text-style: italic; }}
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel the question", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+n", "new_conversation", "New conversation", show=False, priority=True),
        Binding("ctrl+b", "toggle_sidebar", "Panel", show=False, priority=True),
    ]

    def __init__(
        self, think=True, show_thinking=False, animate=True,
        startup=check_startup, agent=run_agent, store=CONVERSATIONS_DIR,
    ):
        super().__init__(ansi_color=True)  # the terminal's own colors and background
        self.think = think
        self.show_thinking = show_thinking
        self.animate = animate
        self.startup = startup
        self.agent = agent
        self.busy = False  # True while Qwen answers a question
        self.question_id = 0  # number of the current question; Esc moves to the next one
        self.events = []  # events of the last question, for /trace
        self.spinner_timer = None
        self.banner_timer = None
        self.store = store  # folder of the saved conversations
        self.conversation = conversations.new_conversation()
        self.question = ""  # text of the question being answered
        self.status = None  # last StartupStatus, for the panel

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="main"):
                yield VerticalScroll(id="history")
                yield Static(id="status")
                yield QuestionBox(placeholder=PLACEHOLDER, highlight_cursor_line=False, id="question")
                yield Static(HINT, id="hint")
                yield Static(ui.DATA_LIMITS, id="limits")  # brick 8, always visible
            yield Sidebar(id="sidebar")

    def on_mount(self):
        if self.size.width < SIDEBAR_MIN_SCREEN:
            self.query_one(Sidebar).add_class("-hidden")
        self.refresh_sidebar()
        self.query_one(QuestionBox).focus()
        self.set_status(Text("Checking the server and the data…", style=theme.MUTED))
        self.in_background(self.startup_thread)

    # --- helpers

    def in_background(self, target, *args):
        """Run blocking work (ping, model calls) in a daemon thread, so the screen stays
        responsive and quitting never waits for a slow model answer."""
        threading.Thread(target=target, args=args, daemon=True).start()

    def from_thread(self, callback, *args):
        """Run `callback` on the app's thread (Textual widgets must not be touched from others)."""
        try:
            self.call_from_thread(callback, *args)
        except RuntimeError:  # the app has already quit
            pass

    def add(self, renderable, widget_id=None):
        """Add one block at the end of the history.

        If the user was reading the end, follow the new block; if they scrolled
        up to read something older, stay there. Short content stays at the top.
        """
        history = self.query_one("#history")
        at_end = history.scroll_y >= history.max_scroll_y - 1
        widget = Static(renderable, id=widget_id)
        history.mount(widget)
        if at_end:
            history.call_after_refresh(history.scroll_end, animate=False)
        return widget

    def set_status(self, renderable):
        self.query_one("#status", Static).update(renderable)

    def width(self):
        """Usable width of the history, for the banner and the board."""
        return max(self.query_one("#history").size.width - 2, 40)

    # --- startup banner

    def refresh_sidebar(self):
        """Show the latest session state and conversations in the panel."""
        sidebar = self.query_one(Sidebar)
        sidebar.show_session(self.status, self.think)
        sidebar.show_conversations(self.conversation, conversations.list_conversations(self.store))

    def startup_thread(self):
        status = self.startup()
        self.from_thread(self.show_banner, status)

    def show_banner(self, status):
        """Animated banner: the train arrives, then the departure board flips."""
        self.status = status
        self.refresh_sidebar()
        self.set_status("")
        width = self.width()
        first = 0.0 if self.animate else TRAIN_END
        self.banner = self.add(self.banner_at(first, status, width), widget_id="banner")
        if self.animate:
            start = time.monotonic()
            self.banner_timer = self.set_interval(
                1 / ui.FPS, lambda: self.tick_banner(time.monotonic() - start, status, width)
            )
        mode = "on" if self.think else "off"
        self.add(Text(f"Model thinking: {mode} · /help for the commands", style=theme.MUTED))

    def banner_at(self, t, status, width):
        """The banner at time t: train first, then the board with the split-flap reveal."""
        train = ui.frame(min(t, ui.TRAIN_ANIM_S), status, width, pixels=True)
        if t < ui.TRAIN_ANIM_S:
            return train
        reveal = min((t - ui.TRAIN_ANIM_S) / ui.FLAP_ANIM_S, 1.0)
        return Group(train, Text(), ui.board(status, width, reveal=reveal, seed=int(t * ui.FPS)))

    def tick_banner(self, t, status, width):
        self.banner.update(self.banner_at(min(t, TRAIN_END), status, width))
        if t >= TRAIN_END:
            self.banner_timer.stop()

    # --- questions

    def on_question_box_submitted(self, message):
        text = message.text.strip()
        if not text:
            return
        if text.startswith("/"):
            self.query_one(QuestionBox).clear()
            self.run_command(text.lower())
            return
        if self.busy:
            self.notify("Qwen is already answering a question. Press Esc to cancel it.", severity="warning")
            return
        self.query_one(QuestionBox).clear()
        self.add(user_line(text))
        self.busy = True
        self.question = text
        self.question_id += 1
        self.events = []
        self.in_background(self.question_thread, text, self.question_id)

    def question_thread(self, question, question_id):
        """Runs in the background: the agent loop, its events sent to the app's thread."""
        def on_event(event):
            if question_id != self.question_id:  # abandoned with Esc: stop this agent
                raise QuestionCancelled
            self.from_thread(self.show_current_event, event, question_id)

        try:
            result = self.agent(question, think=self.think, on_event=on_event)
        except QuestionCancelled:
            return  # the screen already said "Question cancelled."
        except ConnectionError:
            self.from_thread(self.finish, None, f"The model server does not answer. Run: {ui.SERVER_FIX_COMMAND}", question_id)
        except RuntimeError as error:
            self.from_thread(self.finish, None, str(error), question_id)
        else:
            self.from_thread(self.finish, result, None, question_id)

    def show_current_event(self, event, question_id):
        """Show an agent event, unless its question was abandoned in the meantime."""
        if question_id == self.question_id:
            self.show_event(event)

    def show_event(self, event, full=False):
        """Draw one live agent event (the spinner for Thinking). full=True: /trace."""
        if not full:
            self.events.append(event)
            if isinstance(event, Thinking):
                self.start_spinner(event.step)
                return
            self.stop_spinner()
        renderable = self.render_event(event, full)
        if renderable is not None:
            self.add(renderable)

    def render_event(self, event, full=False):
        """The block for one event (None if nothing to show), with the ui.py renderers."""
        if isinstance(event, Thinking):
            return Text(f"— Step {event.step}: Qwen is thinking —", style=theme.MUTED) if full else None
        if isinstance(event, Reasoning) and not (self.show_thinking or full):
            return None
        if isinstance(event, FinalAnswer):
            return Group(ui.render_answer(event), ui.render_sources(event))
        renderers = {
            "ToolCall": ui.render_tool_call,
            "ToolResult": lambda e: ui.render_tool_result(e, max_lines=None if full else ui.MAX_RESULT_LINES),
            "ConfidenceInterval": ui.render_interval,
            "GuardVerdict": ui.render_guard,
            "Reasoning": ui.render_reasoning,
        }
        return renderers[type(event).__name__](event)

    def finish(self, result, error, question_id):
        """The question is over: summary line, or the error message. Then save it."""
        if question_id != self.question_id:  # abandoned with Esc: already handled
            return
        self.stop_spinner()
        self.busy = False
        if error:
            self.add(Text(error, style=theme.ERROR))
        else:
            self.add(ui.render_result(result))
        self.save_question(result, error)

    def save_question(self, result, message):
        """Add the finished question to the current conversation and save it on disk."""
        conversations.add_question(self.conversation, self.question, self.events, result, message)
        conversations.save(self.conversation, self.store)
        self.refresh_sidebar()

    def start_spinner(self, step):
        spinner = ui.TrainSpinner(step)
        self.set_status(spinner)
        self.spinner_timer = self.set_interval(1 / ui.SPINNER_FPS, lambda: self.set_status(spinner))

    def stop_spinner(self):
        if self.spinner_timer:
            self.spinner_timer.stop()
            self.spinner_timer = None
        self.set_status("")

    def action_cancel(self):
        """Esc: abandon the question at once. Its thread finishes the current model
        call in the background (an HTTP request can't be cut), then stops; nothing
        it sends is shown any more."""
        if not self.busy:
            return
        self.question_id += 1  # the running thread is now an old question
        self.busy = False
        self.stop_spinner()
        self.add(Text("Question cancelled.", style=theme.ERROR))
        self.save_question(None, "Question cancelled.")

    # --- conversations (panel and shortcuts)

    def clear_history(self, header):
        """Empty the history (new or reopened conversation) and show a header line."""
        self.query_one("#history").remove_children()
        self.add(header)

    def can_switch(self):
        if self.busy:
            self.notify("Qwen is answering a question. Press Esc to cancel it first.", severity="warning")
        return not self.busy

    def action_new_conversation(self):
        """Ctrl+N or "+ New conversation": an empty conversation, saved at its first question."""
        if not self.can_switch():
            return
        self.conversation = conversations.new_conversation()
        self.events = []
        self.clear_history(Text("New conversation · ask a question or pick an example on the right.", style=theme.MUTED))
        self.refresh_sidebar()
        self.query_one(QuestionBox).focus()

    def open_conversation(self, conversation_id):
        """Show a saved conversation again (no model call). New questions continue it."""
        if not self.can_switch():
            return
        self.conversation = conversations.load(conversation_id, self.store)
        date = self.conversation["updated"].replace("T", " ")[:16]
        self.clear_history(Text.assemble(
            ("Conversation · ", theme.MUTED), (self.conversation["title"], f"bold {theme.ACCENT}"), (f" · {date}", theme.MUTED),
        ))
        for saved in self.conversation["questions"]:
            self.events = [conversations.event_from_dict(data) for data in saved["events"]]
            self.add(user_line(saved["question"]))
            for event in self.events:
                renderable = self.render_event(event)
                if renderable is not None:
                    self.add(renderable)
            if saved["result"]:
                self.add(ui.render_result(saved["result"]))
            elif saved["message"]:
                self.add(Text(saved["message"], style=theme.ERROR))
        self.refresh_sidebar()
        self.query_one(QuestionBox).focus()

    def action_toggle_sidebar(self):
        self.query_one(Sidebar).toggle_class("-hidden")

    def on_sidebar_new_conversation(self, message):
        self.action_new_conversation()

    def on_sidebar_open_conversation(self, message):
        self.open_conversation(message.conversation_id)

    def on_sidebar_use_starter(self, message):
        """A starter question goes into the box: the user can edit it, then press Enter."""
        box = self.query_one(QuestionBox)
        box.text = message.question
        box.move_cursor(box.document.end)
        box.focus()

    # --- /commands

    def run_command(self, command):
        if command in QUIT_COMMANDS:
            self.exit()
        elif command == "/help":
            self.add(ui.render_help())
        elif command == "/trace":
            if not self.events:
                self.add("No question yet.")
            for event in list(self.events):
                self.show_event(event, full=True)
        elif command == "/log":
            rows = read_cleaning_log()
            if rows:
                self.add(ui.render_log(rows))
            else:
                self.add(Text(f"No cleaning log. Run: {ui.DATA_FIX_COMMAND}", style=theme.ERROR))
        elif command == "/status":
            self.set_status(Text("Checking the server and the data…", style=theme.MUTED))
            self.in_background(self.status_thread)
        else:
            self.add(Text(f"Unknown command: {command}. Type /help.", style=theme.ERROR))

    def status_thread(self):
        status = self.startup()
        self.from_thread(self.show_status, status)

    def show_status(self, status):
        self.set_status("")
        lines = [ui.board(status, self.width()), Text(), ui.arrival_badge(status)]
        lines += [Text(f"→ To fix: {command}", style=theme.ERROR) for command in ui.fix_commands(status)]
        self.add(Group(*lines))


TRAIN_END = ui.TRAIN_ANIM_S + ui.FLAP_ANIM_S  # end of the banner animation
