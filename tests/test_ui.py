"""Tests for the display (ui.py). They never call the model, never start the
server and never wait for an animation: events are written by hand."""

import io
import math
import re
import time
from pathlib import Path
from datetime import datetime

import pytest
from rich.console import Console
from rich.text import Text

from tgv_analyst import ui
from tgv_analyst.config import EARLY_S, LATE_S
from tgv_analyst.events import FinalAnswer, GuardVerdict, StartupStatus, Thinking, ToolCall, ToolResult



def make_status(server_ok=True, latency=1.0, data_ok=True, n_rows=12792, model="qwen3.5-4b-16k"):
    return StartupStatus(
        server_ok=server_ok,
        latency_s=latency if server_ok else None,
        data_ok=data_ok,
        n_rows=n_rows if data_ok else None,
        model_name=model,
        endpoint="localhost:11434",
        guard_enabled=True,
    )


def render(renderable, width=100):
    """Text of a rich object, as a 100-column terminal without colors would show it."""
    console = Console(record=True, width=width, force_terminal=False, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


# 1. classify_arrival, including the exact thresholds
@pytest.mark.parametrize("latency, expected", [
    (0.0, ui.Arrival.EARLY),
    (EARLY_S - 0.001, ui.Arrival.EARLY),
    (EARLY_S, ui.Arrival.ON_TIME),  # 0.5 s is not "< 0.5 s"
    (LATE_S, ui.Arrival.ON_TIME),  # 3 s is still "<= 3 s"
    (LATE_S + 0.001, ui.Arrival.LATE),
])
def test_classify_arrival_thresholds(latency, expected):
    assert ui.classify_arrival(make_status(latency=latency)) is expected


def test_classify_arrival_cancelled():
    assert ui.classify_arrival(make_status(server_ok=False)) is ui.Arrival.CANCELLED
    assert ui.classify_arrival(make_status(data_ok=False)) is ui.Arrival.CANCELLED


# 2. CANCELLED shows the command that fixes the problem
def test_cancelled_server_down_shows_server_command():
    text = render(ui.frame(ui.TRAIN_ANIM_S, make_status(server_ok=False), 100))
    assert "Cancelled" in text
    assert ui.SERVER_FIX_COMMAND in text
    assert "download_data.py" not in text


def test_cancelled_data_missing_shows_data_scripts():
    text = render(ui.frame(ui.TRAIN_ANIM_S, make_status(data_ok=False), 100))
    assert "Cancelled" in text
    assert "python scripts/download_data.py && python scripts/clean_data.py" in text
    assert ui.SERVER_FIX_COMMAND not in text


# 3. The board shows the real values
def test_board_shows_row_count_and_model():
    text = render(ui.board(make_status(n_rows=41203, model="mon-modele-test"), 100, now=datetime(2026, 11, 1, 15, 35)))
    assert "41,203 rows" in text
    assert "mon-modele-test" in text
    assert "15:35" in text
    assert "11434" in text  # VOIE = the real port


def test_board_drops_voie_column_when_narrow():
    text = render(ui.board(make_status(), 70), width=70)
    assert "TRACK" not in text
    assert "DESTINATION" in text


# 4. A blocked verdict shows BLOCKED and each rejected number
def test_blocked_guard_lists_rejected_numbers():
    verdict = GuardVerdict(passed=False, checked=["87.3", "12792", "4"], rejected=["87.3", "4"], will_retry=True)
    text = render(ui.render_guard(verdict))
    assert "BLOCKED" in text
    assert "✗ GUARD · BLOCKED · 87.3, 4 never computed" in text
    assert "2nd try" in text
    assert "12792" not in text  # accepted numbers are not listed


def test_passed_guard_counts_numbers():
    text = render(ui.render_guard(GuardVerdict(passed=True, checked=["9.5", "640", "6704"], rejected=[])))
    assert "✓ GUARD · 3 numbers verified" in text


# 5. [n] markers only for numbers that have a source
def test_final_answer_markers():
    answer = FinalAnswer(
        text="In 2024, the rate is **9.5%** (640 trains out of 6704).",
        sources={"9.5": 3, "640": 1},
    )
    text = render(ui.render_answer(answer))
    assert "9.5[1]" in text  # first cited call (call 3) gets marker [1]
    assert "640[2]" in text
    assert "6704[" not in text
    assert "2024[" not in text
    assert "**" not in text
    assert "Sources: [1] call 3 · [2] call 1" in render(ui.render_sources(answer))


# 6. French number format
def test_fmt_number():
    assert ui.fmt_number(41203) == "41,203"
    assert ui.fmt_number(0.842, percent=True) == "84.2%"
    assert ui.fmt_number(1.25, decimals=1) == "1.2"  # Python rounds half to even
    assert ui.fmt_number(12792.0) == "12,792"


# 7. Interval bar: dot at the edges, no crash when low == high
def test_interval_bar_edges():
    left = ui.interval_bar(0.1, 0.1, 0.2)
    right = ui.interval_bar(0.2, 0.1, 0.2)
    assert left.startswith("├●")
    assert right.endswith("●┤")
    assert len(left) == len(right) == ui.BAR_WIDTH + 2


def test_interval_bar_zero_width_interval():
    bar = ui.interval_bar(0.5, 0.5, 0.5)
    assert bar.count("●") == 1
    assert len(bar) == ui.BAR_WIDTH + 2


# 8. --plain: no ANSI codes and no boxes, even on a real terminal
def test_plain_output_has_no_ansi_codes():
    output = io.StringIO()
    console = ui.make_console(plain=True, file=output, force_terminal=True, width=100)
    display = ui.Display(console=console, plain=True, animate=True)
    display.show_startup(make_status(), think=True)
    for event in [
        Thinking(step=1),
        ToolCall(call_id=1, code="print(len(df))"),
        ToolResult(call_id=1, output="12792\n", numbers=[12792.0]),
        GuardVerdict(passed=False, checked=["99"], rejected=["99"], will_retry=True),
        FinalAnswer(text="There are 12792 rows.", sources={"12792": 1}),
    ]:
        display.on_event(event)
    text = output.getvalue()
    assert "\x1b" not in text
    assert "╭" not in text and "│" not in text
    assert "BLOCKED" in text and "12792[1]" in text


# 9. The last animation frame renders alone, without Live and without waiting
def test_last_frame_renders_without_waiting():
    start = time.monotonic()
    text = render(ui.frame(ui.TRAIN_ANIM_S, make_status(latency=1.2), 100))
    assert time.monotonic() - start < 0.5
    assert "TRACK 11434" in text
    assert "On time" in text


def test_train_stops_at_the_right_place():
    width, train = 120, len(ui.SPRITE[0])
    platform_start, platform_end = ui.platform_span(width)
    nose = {a: ui.train_x(ui.TRAIN_ANIM_S, a, width, train) + train for a in ui.Arrival}
    assert nose[ui.Arrival.ON_TIME] == platform_end  # exactly at the platform
    assert nose[ui.Arrival.EARLY] < platform_start  # before the platform
    assert platform_end < nose[ui.Arrival.LATE] <= width  # slightly past it
    assert train <= nose[ui.Arrival.CANCELLED] < nose[ui.Arrival.EARLY]  # mid-track, fully visible
    assert ui.train_x(0, ui.Arrival.ON_TIME, width, train) == -train  # starts off screen


def test_tool_result_truncated_and_error():
    long_output = "\n".join(f"ligne {i}" for i in range(30))
    text = render(ui.render_tool_result(ToolResult(call_id=2, output=long_output)))
    assert "10 more lines, /trace to see everything" in text
    assert "ligne 25" not in text
    full = render(ui.render_tool_result(ToolResult(call_id=2, output=long_output), max_lines=None))
    assert "ligne 29" in full
    failed = render(ui.render_tool_result(ToolResult(call_id=3, output="Error: x", error="NameError: x")))
    assert "error" in failed and "NameError: x" in failed


def test_tabular_output_becomes_a_table():
    output = "      year  taux\n0     2023  0.12\n1     2024  0.13\n"
    assert ui.parse_table(output) == [["", "year", "taux"], ["0", "2023", "0.12"], ["1", "2024", "0.13"]]
    assert ui.parse_table("Rows: 12792\nMonths: 2018-01 to 2026-06") is None


def test_rejected_year_has_no_thousands_separator():
    text = render(ui.render_guard(GuardVerdict(passed=False, checked=["2018"], rejected=["2018"])))
    assert "✗ GUARD · BLOCKED · 2018 never computed" in text


# --- UI pass 2 ---------------------------------------------------------------

# 1. Sprite rows all have the same width and only use palette keys
@pytest.mark.parametrize("rows", [ui.SPRITE, ui.SPRITE_TWO_CARS, ui.SPRITE_SHORT])
def test_sprite_grid_is_valid(rows):
    keys = set(ui.sprite_palette(None))
    assert len({len(row) for row in rows}) == 1
    assert all(set(row) <= keys for row in rows)


# 2. Two pixel rows per terminal line
def test_sprite_renders_two_pixel_rows_per_line():
    palette = ui.sprite_palette(None)
    assert len(ui.render_sprite(ui.SPRITE, palette)) == math.ceil(len(ui.SPRITE) / 2)
    assert len(ui.render_sprite(ui.SPRITE[:3], palette)) == 2  # odd number of rows


# 3. Transparent pixels never get a background
def test_transparent_pixel_pair_has_no_background():
    assert ui.pixel_pair(None, None) == (" ", None)
    top_char, top_style = ui.pixel_pair("top", None)
    bottom_char, bottom_style = ui.pixel_pair(None, "bottom")
    assert (top_char, top_style) == ("▀", "top") and (bottom_char, bottom_style) == ("▄", "bottom")
    line = ui.render_sprite(["..", ".."], ui.sprite_palette(None))[0]
    assert line.plain == "  " and not line.spans


# 4. --plain and NO_COLOR: ASCII train, no ANSI codes
def test_plain_uses_ascii_train():
    output = io.StringIO()
    console = ui.make_console(plain=True, file=output, force_terminal=True, width=100)
    display = ui.Display(console=console, plain=True)
    display.show_startup(make_status(), think=True)
    assert not display.pixels
    assert "(o)" in output.getvalue()
    assert "\x1b" not in output.getvalue()


def test_no_color_uses_ascii_train(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    output = io.StringIO()
    display = ui.Display(console=ui.make_console(file=output, force_terminal=True, width=100), animate=False)
    display.show_startup(make_status(), think=True)
    assert not display.pixels
    assert "(o)" in output.getvalue()
    assert "\x1b" not in output.getvalue()


def test_truecolor_terminal_uses_pixel_train():
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system="truecolor", width=100)
    display = ui.Display(console=console, animate=False)
    display.show_startup(make_status(), think=True)
    assert display.pixels
    assert "▀" in output.getvalue() and "(o)" not in output.getvalue()


# 5. Nothing to check: neutral badge, not a success
def test_guard_with_nothing_to_check_is_neutral():
    text = render(ui.render_guard(GuardVerdict(passed=True, checked=[], rejected=[])))
    assert "○ GUARD · no number to check" in text
    assert "✓" not in text


# 6. French plural
def test_plural():
    assert ui.plural(1, "step", "steps") == "step"
    assert ui.plural(2, "step", "steps") == "steps"
    assert ui.plural(0, "step", "steps") == "steps"  # English: "0 steps"
    summary = render(ui.render_summary({"status": "ok", "trace": {"turns": 1, "seconds": 2.0, "tokens": 1}}))
    assert "1 step ·" in summary and "1 token" in summary


# 7. No color literal in ui.py: every color comes from theme.py
COLOR_NAMES = (
    "red", "green", "blue", "yellow", "cyan", "magenta", "white", "black",
    "grey", "gray", "orange", "purple", "pink", "amber",
)


@pytest.mark.parametrize("module", ["ui.py", "app.py", "sidebar.py"])
def test_no_color_literal_outside_theme(module):
    source = (Path(ui.__file__).parent / module).read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{6}\b", source), f"hex color in {module}"
    assert "rgb(" not in source
    names = "|".join(COLOR_NAMES)
    in_string = re.compile(r"[\"'][^\"'\n]*\b(?:" + names + r")\d*\b[^\"'\n]*[\"']")
    found = [m.group(0) for m in in_string.finditer(source)]
    assert not found, f"color names in {module} strings: {found}"


def test_number_of_cars_follows_terminal_width():
    assert ui.sprite_for_width(120) is ui.SPRITE  # 3 cars
    assert len(ui.sprite_for_width(100)[0]) < len(ui.SPRITE[0])  # 2 cars
    assert ui.sprite_for_width(70) is ui.SPRITE_SHORT  # power car only
    for width in (80, 100, 120):  # arrival positions stay distinct at every width
        train = len(ui.sprite_for_width(width)[0])
        stops = {ui.train_x(ui.TRAIN_ANIM_S, a, width, train) for a in ui.Arrival}
        assert len(stops) == 4


def test_question_box_is_full_width(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "  ma question ")
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system="truecolor", width=60)
    assert ui.Display(console=console).read_question() == "  ma question "
    lines = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue()).split("\n")
    assert lines[0] == "╭" + "─" * 58 + "╮"
    assert lines[1].startswith("│ › ") and lines[1].endswith("│") and len(lines[1]) == 60
    assert lines[2] == "╰" + "─" * 58 + "╯"


def test_plain_prompt_has_no_box(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *args: "q")
    output = io.StringIO()
    display = ui.Display(console=ui.make_console(plain=True, file=output, width=60), plain=True)
    assert display.read_question() == "q"
    assert "╭" not in output.getvalue()


def test_backslash_continues_the_question_on_a_new_line(monkeypatch):
    typed = iter(["Compare 2023 \\", "et 2024", "ignored"])
    monkeypatch.setattr("builtins.input", lambda: next(typed))
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system="truecolor", width=60)
    assert ui.Display(console=console).read_question() == "Compare 2023 \net 2024"
    screen = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue())
    assert "│ › Compare 2023 " in screen  # first line kept in the box after the new line
    assert "\x1b[J" in screen  # the box was erased and redrawn one line taller


def test_banner_does_not_touch_the_top():
    output = io.StringIO()
    display = ui.Display(console=ui.make_console(plain=True, file=output, width=100), plain=True)
    display.show_startup(make_status(), think=True)
    assert output.getvalue().startswith("\n" * ui.TOP_MARGIN)


def test_data_limits_printed_once_after_the_banner():
    """Line-by-line and one-question modes: brick 8 limits once, after the banner."""
    output = io.StringIO()
    display = ui.Display(console=ui.make_console(plain=True, file=output, width=200), plain=True)
    display.show_startup(make_status(), think=True)
    text = output.getvalue()
    assert text.count(ui.DATA_LIMITS) == 1
    assert text.index("Model thinking") < text.index(ui.DATA_LIMITS)


def test_data_limits_text():
    """The two limits of data/RULES.md, and no number."""
    assert "why trains were late" in ui.DATA_LIMITS
    assert "not SNCF's official national rate" in ui.DATA_LIMITS  # RULES.md, rule 2
    assert not any(char.isdigit() for char in ui.DATA_LIMITS)


def test_help_lists_the_copy_and_paste_keys():
    terminal = render(ui.render_help())  # line-by-line mode: the terminal's keys
    assert "ctrl+shift+c" in terminal and "ctrl+shift+v" in terminal
    app = render(ui.render_help(ui.APP_KEYS))  # full-screen app: the app selects and copies
    assert "drag to the top or bottom edge to scroll" in app and "ctrl+c" in app


def test_to_text_draws_a_panel_as_styled_text():
    """The app's history is Text so the mouse can select it: same lines, same colors."""
    from rich.panel import Panel

    panel = Panel("9.5 % of trains were late", title="Answer", border_style=ui.theme.ACCENT)
    text = ui.to_text(panel, 40)
    lines = text.plain.split("\n")
    assert len(lines) == 3  # top border, the line, bottom border
    assert all(len(line) <= 40 for line in lines)
    assert "Answer" in lines[0] and "9.5 % of trains were late" in lines[1]
    assert text.spans  # the colors are kept


def test_to_text_wraps_to_the_width():
    text = ui.to_text(Text("word " * 20), 30)
    assert all(len(line) <= 30 for line in text.plain.split("\n"))
    assert len(text.plain.split("\n")) >= 3
