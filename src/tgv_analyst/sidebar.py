"""Right-side panel of the app (like the sidebar of opencode), kept short:
session, "+ New conversation", saved conversations, a few starter questions.

It only displays and reports clicks: it posts a message (NewConversation,
OpenConversation, UseStarter) and the app decides what to do.
"""

from datetime import datetime

from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from tgv_analyst import theme, ui

NEW_ID = "new"  # option id of "+ New conversation"
MAX_LISTED = 30  # conversations shown in the list

STARTERS = [
    "Delay rate Paris Lyon → Marseille St Charles in 2024?",
    "Which route had the most delays in 2025?",
    "Main causes of delays in 2024?",
]
SHORTCUTS = "ctrl+n new · ctrl+b hide\nshift+drag select · ctrl+shift+v paste"


def section(title):
    """Section heading, in the accent color."""
    return Static(Text(title, style=f"bold {theme.ACCENT}"), classes="section")


def conversation_option(conversation, current_id):
    """One entry of the list: title, then its date in muted text."""
    marker = ("● ", theme.ACCENT) if conversation["id"] == current_id else ("  ", "")
    date = datetime.fromisoformat(conversation["updated"]).strftime("%b %d, %H:%M")
    prompt = Text.assemble(marker, conversation["title"] or "(untitled)", "\n  ", (date, theme.MUTED))
    return Option(prompt, id=conversation["id"])


def session_text(status, think):
    """Top of the panel: app name, model and thinking mode, server state."""
    lines = Text.assemble(
        ("TGV Analyst", f"bold {theme.ACCENT}"), "\n",
        (f"{status.model_name if status else '…'} · thinking {'on' if think else 'off'}", theme.MUTED),
    )
    if status:
        lines.append("\n")
        lines.append_text(ui.arrival_badge(status))
    return lines


class Sidebar(VerticalScroll):
    """The panel. The app calls show_session() and show_conversations() to update it."""

    class NewConversation(Message):
        """The user clicked "+ New conversation"."""

    class OpenConversation(Message):
        def __init__(self, conversation_id):
            super().__init__()
            self.conversation_id = conversation_id

    class UseStarter(Message):
        def __init__(self, question):
            super().__init__()
            self.question = question

    def compose(self):
        yield Static(id="session")
        yield section("CONVERSATIONS")
        yield OptionList(id="conversations")
        yield section("TRY")
        starters = [Option(Text.assemble(("› ", theme.ACCENT), q), id=str(i)) for i, q in enumerate(STARTERS)]
        yield OptionList(*starters, id="starters")
        yield Static(Text(SHORTCUTS, style=theme.MUTED), classes="section")

    def show_session(self, status, think):
        self.query_one("#session", Static).update(session_text(status, think))

    def show_conversations(self, current, saved):
        """Update the list: "+ New conversation", then the saved ones (most recent first)."""
        options = self.query_one("#conversations", OptionList)
        options.clear_options()
        options.add_option(Option(Text("+ New conversation", style=f"bold {theme.ACCENT}"), id=NEW_ID))
        for conversation in saved[:MAX_LISTED]:
            options.add_option(conversation_option(conversation, current["id"]))

    def on_option_list_option_selected(self, event):
        event.stop()
        if event.option_list.id == "starters":
            self.post_message(self.UseStarter(STARTERS[int(event.option.id)]))
        elif event.option.id == NEW_ID:
            self.post_message(self.NewConversation())
        else:
            self.post_message(self.OpenConversation(event.option.id))
