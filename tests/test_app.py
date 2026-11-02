"""Tests for the full-screen app (app.py), with Textual's test pilot.

The model and the server are replaced by fake functions: these tests never
call Qwen, never ping a server and never wait for the banner animation.
"""

import asyncio
import io
import tempfile
import time
from pathlib import Path

from rich.console import Console

from tgv_analyst import ui
from tgv_analyst.app import QuestionBox, TgvApp
from tgv_analyst.events import FinalAnswer, GuardVerdict, StartupStatus, Thinking, ToolCall, ToolResult

STATUS = StartupStatus(True, 0.01, True, 12792, "qwen-test", "localhost:11434", True)


def new_store():
    """A fresh temporary folder for saved conversations (never the real conversations/)."""
    return Path(tempfile.mkdtemp(prefix="tgv-test-"))


def fake_startup():
    return STATUS


def fake_agent(question, think, on_event):
    """Plays the events of a short question, like run_agent would."""
    on_event(Thinking(step=1))
    on_event(ToolCall(call_id=1, code="print(len(df))"))
    on_event(ToolResult(call_id=1, output="12792\n", numbers=[12792.0]))
    on_event(GuardVerdict(passed=True, checked=["12792"], rejected=[]))
    on_event(FinalAnswer(text="There are 12792 rows.", sources={"12792": 1}))
    return {"status": "ok", "answer": "There are 12792 rows.", "trace": {"turns": 2, "seconds": 1.0, "tokens": 10}}


def history_text(app):
    """All the text in the history, as a 120-column terminal would show it."""
    console = Console(record=True, width=120, file=io.StringIO())
    for widget in app.query_one("#history").children:
        console.print(widget.content)
    return console.export_text()


async def wait_for(pilot, condition, timeout=5):
    """Let the app run until `condition()` is true (background threads need a moment)."""
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        await pilot.pause(0.05)


def run(scenario):
    """Run one scenario in a 120x40 test app with the fake startup and agent."""
    async def main():
        app = TgvApp(animate=False, startup=fake_startup, agent=fake_agent, store=new_store())
        async with app.run_test(size=(120, 40)) as pilot:
            await wait_for(pilot, lambda: app.query("#banner"))
            await scenario(app, pilot)
        return app
    return asyncio.run(main())


def test_banner_shows_the_startup_status():
    async def scenario(app, pilot):
        text = history_text(app)
        assert "TRACK 11434" in text and "qwen-test" in text and "Early" in text
    run(scenario)


def test_enter_sends_the_question_and_shows_every_step():
    async def scenario(app, pilot):
        app.query_one(QuestionBox).insert("How many rows?")
        await pilot.press("enter")
        await wait_for(pilot, lambda: not app.busy and "verified answer" in history_text(app))
        text = history_text(app)
        assert "› How many rows?" in text
        assert "Tool call [1] · run_python" in text
        assert "✓ GUARD · 1 number verified" in text
        assert "12792[1]" in text
        assert app.query_one(QuestionBox).text == ""  # the box is emptied after sending
    run(scenario)


def test_backslash_enter_adds_a_new_line_instead_of_sending():
    async def scenario(app, pilot):
        box = app.query_one(QuestionBox)
        box.insert("Compare 2023 \\")
        await pilot.press("enter")
        box.insert("et 2024")
        assert box.text == "Compare 2023 \net 2024"
        assert not app.busy  # nothing was sent
    run(scenario)


def test_unknown_command_and_help():
    async def scenario(app, pilot):
        box = app.query_one(QuestionBox)
        box.insert("/help")
        await pilot.press("enter")
        box.insert("/nimporte")
        await pilot.press("enter")
        text = history_text(app)
        assert "/trace" in text and "Unknown command: /nimporte" in text
    run(scenario)


def test_quit_command_exits():
    async def scenario(app, pilot):
        app.query_one(QuestionBox).insert("/quit")
        await pilot.press("enter")
        await pilot.pause()
        assert app.return_code is not None or not app.is_running
    run(scenario)


def test_banner_starts_at_the_top():
    async def scenario(app, pilot):
        await pilot.pause(0.2)
        assert app.query_one("#banner").region.y == ui.TOP_MARGIN  # top margin, not stuck to the bottom
    run(scenario)


def slow_agent(question, think, on_event):
    """A model call that takes 3 s, then events that must not appear after Esc."""
    on_event(Thinking(step=1))
    time.sleep(3)
    on_event(FinalAnswer(text="Trop tard.", sources={}))
    return {"status": "ok", "answer": "Trop tard.", "trace": {"turns": 1, "seconds": 3.0, "tokens": 1}}


def test_escape_cancels_at_once():
    async def main():
        app = TgvApp(animate=False, startup=fake_startup, agent=slow_agent, store=new_store())
        async with app.run_test(size=(120, 40)) as pilot:
            await wait_for(pilot, lambda: app.query("#banner"))
            app.query_one(QuestionBox).insert("Question lente")
            await pilot.press("enter")
            await wait_for(pilot, lambda: app.busy)
            start = time.monotonic()
            await pilot.press("escape")
            await pilot.pause(0.1)
            assert time.monotonic() - start < 1  # no waiting for the model
            assert not app.busy
            assert "Question cancelled." in history_text(app)
            await pilot.pause(3.5)  # the abandoned thread finishes...
            assert "Trop tard." not in history_text(app)  # ...but nothing it sends is shown
    asyncio.run(main())


def test_history_follows_new_content_when_it_overflows():
    async def main():
        app = TgvApp(animate=False, startup=fake_startup, agent=fake_agent, store=new_store())
        async with app.run_test(size=(120, 24)) as pilot:  # small screen: content overflows
            await wait_for(pilot, lambda: app.query("#banner"))
            app.query_one(QuestionBox).insert("How many rows?")
            await pilot.press("enter")
            await wait_for(pilot, lambda: not app.busy)
            await pilot.pause(0.3)
            history = app.query_one("#history")
            assert history.max_scroll_y > 0 and history.scroll_y == history.max_scroll_y
    asyncio.run(main())


# --- side panel and conversations ---------------------------------------------

def ask(app, pilot, question):
    """Type a question, send it and wait for the answer."""
    async def go():
        app.query_one(QuestionBox).insert(question)
        await pilot.press("enter")
        await wait_for(pilot, lambda: not app.busy and app.conversation["questions"])
        await pilot.pause(0.2)
    return go()


def sidebar_text(app):
    console = Console(record=True, width=60, file=io.StringIO())
    for widget in app.query("Sidebar Static"):
        console.print(widget.content)
    for options in app.query("Sidebar OptionList"):
        for i in range(options.option_count):
            console.print(options.get_option_at_index(i).prompt)
    return console.export_text()


def test_question_is_saved_and_listed_in_the_panel():
    async def scenario(app, pilot):
        await ask(app, pilot, "How many rows?")
        saved = list(app.store.glob("*.json"))
        assert len(saved) == 1
        text = sidebar_text(app)
        assert "How many rows?" in text and "+ New conversation" in text
        assert "TGV Analyst" in text and "qwen-test" in text
    run(scenario)


def test_new_conversation_then_reopen_the_old_one():
    async def scenario(app, pilot):
        await ask(app, pilot, "How many rows?")
        first_id = app.conversation["id"]
        await pilot.press("ctrl+n")
        await pilot.pause(0.1)
        assert app.conversation["id"] != first_id
        assert "How many rows?" not in history_text(app)  # history emptied
        app.open_conversation(first_id)
        await pilot.pause(0.2)
        text = history_text(app)
        assert "› How many rows?" in text and "12792[1]" in text  # replayed, no model call
        assert "verified answer" in text
    run(scenario)


def test_starter_question_fills_the_box():
    async def scenario(app, pilot):
        starters = app.query_one("#starters")
        starters.highlighted = 0
        starters.action_select()
        await pilot.pause(0.1)
        box = app.query_one(QuestionBox)
        assert box.text.startswith("Delay rate Paris Lyon")
        assert box.has_focus and not app.busy  # filled, not sent
    run(scenario)


def test_ctrl_b_hides_and_shows_the_panel():
    async def scenario(app, pilot):
        sidebar = app.query_one("Sidebar")
        assert sidebar.display
        await pilot.press("ctrl+b")
        assert not sidebar.display
        await pilot.press("ctrl+b")
        assert sidebar.display
    run(scenario)


def test_data_limits_always_under_the_question_box():
    """Brick 8: what the data can't conclude, shown once like "Claude can make mistakes",
    not inside the answers (so never under a greeting or a goodbye)."""
    async def scenario(app, pilot):
        limits = app.query_one("#limits")
        assert str(limits.render()) == ui.DATA_LIMITS
        assert limits.region.y > app.query_one(QuestionBox).region.y  # below the box
        app.query_one(QuestionBox).insert("How many rows?")
        await pilot.press("enter")
        await wait_for(pilot, lambda: not app.busy and "verified answer" in history_text(app))
        assert "why trains were late" not in history_text(app)  # not repeated in the answer
    run(scenario)


def test_ctrl_v_with_empty_app_clipboard_shows_how_to_paste(monkeypatch):
    """A terminal app can't read the system clipboard: Ctrl+V explains the terminal's paste key."""
    notices = []

    async def scenario(app, pilot):
        monkeypatch.setattr(app, "notify", lambda message, **kwargs: notices.append(message))
        app.query_one(QuestionBox).focus()
        await pilot.press("ctrl+v")
        assert notices == [ui.PASTE_TIP]
        assert app.query_one(QuestionBox).text == ""
    run(scenario)


def test_ctrl_v_pastes_text_copied_inside_the_app():
    async def scenario(app, pilot):
        app.copy_to_clipboard("Paris Lyon")
        box = app.query_one(QuestionBox)
        box.focus()
        await pilot.press("ctrl+v")
        assert box.text == "Paris Lyon"
    run(scenario)


def test_terminal_paste_goes_into_the_question_box():
    """Ctrl+Shift+V: the terminal sends the clipboard as a paste event."""
    from textual import events

    async def scenario(app, pilot):
        box = app.query_one(QuestionBox)
        box.focus()
        app.post_message(events.Paste("Taux de retard 2024 ?"))  # like the terminal: to the app
        await pilot.pause()
        assert box.text == "Taux de retard 2024 ?"
    run(scenario)
