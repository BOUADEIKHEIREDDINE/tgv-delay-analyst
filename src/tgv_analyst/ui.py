"""Terminal display (rich): startup banner, tool calls, guard verdict, answer.

This file only displays. It never calls the model, the tools or the guard:
it receives events (events.py) from the agent and draws them. cli.py
connects the two. All colors come from theme.py. Everything is in English.

Order of the file:
1. constants (sizes, drawings, texts)
2. pure functions (formatting, arrival state, interval bar): easy to test
3. train drawing (pixel sprite or ASCII) and banner frame
4. renderers: event -> rich object, without printing
5. Display: prints the renderers, runs the animations and the spinner
6. preview: python -m tgv_analyst.ui --preview
"""

import argparse
import io
import os
import random
import re
import time
from contextlib import nullcontext
from datetime import datetime
from enum import Enum
from functools import lru_cache

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from tgv_analyst import theme
from tgv_analyst.config import EARLY_S, LATE_S
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
from tgv_analyst.guard import NUMBER_PATTERN  # same number reading as the guard

# ---------------------------------------------------------------- 1. constants

# Sizes and timings.
FPS = 20  # animation frames per second
TRAIN_ANIM_S = 1.5  # the train crosses the screen in this time
FLAP_ANIM_S = 0.6  # departure board "split-flap" reveal
SPINNER_FPS = 10
MIN_ANIM_WIDTH = 60  # narrower terminal: no animation
WIDE_WIDTH = 80  # narrower terminal: power car only, no VOIE column
THREE_CARS_WIDTH = 110  # narrower terminal (80 to 109 columns): two cars
SCENE_MAX_WIDTH = 120
PLATFORM_WIDTH = 16
PLATFORM_MARGIN = 6  # track after the platform, so a late train can stop past it
LATE_OVERSHOOT = 3  # a late train stops this many columns past the platform
MAX_RESULT_LINES = 20  # tool output shown during a question (/trace shows everything)
BAR_WIDTH = 21  # characters between the two ends of the interval bar

PROMPT_MARK = "› "  # inside the question box, on the first line
CONTINUE_MARK = "  "  # same width, on the next lines
NEW_LINE_KEY = "\\"  # a line ending with \ continues on a new line (like Claude Code)
PROMPT_HINT = "enter send · \\ + enter new line · /help · /quit"
# Brick 8: what the data can't conclude (sources: data/RULES.md). Shown once, like
# "Claude can make mistakes": under the question box in the app, after the banner
# in the line-by-line modes. Written in code, not by the model, so it's always right.
DATA_LIMITS = (
    "Monthly totals per route: they don't say why trains were late, or whether your "
    "train will be. A sum over routes is not SNCF's official national rate."
)
TOP_MARGIN = 4  # blank lines above the banner, so the train doesn't touch the top
PLAIN_PROMPT = "Question > "

# ANSI cursor moves, used only to put the cursor back inside the question box.
CURSOR_UP = "\x1b[{}A"
CURSOR_DOWN = "\x1b[{}B"
CURSOR_RIGHT = "\x1b[{}C"
CLEAR_TO_END = "\x1b[J"  # erase from the cursor to the end of the screen

SERVER_FIX_COMMAND = "ollama serve"
DATA_FIX_COMMAND = "python scripts/download_data.py && python scripts/clean_data.py"

COMMANDS = [
    ("/help", "list the commands"),
    ("/trace", "every step of the last question, in full"),
    ("/log", "the data cleaning log (data/cleaning_log.csv)"),
    ("/status", "check the server and the data again"),
    ("/quit", "quit (also Ctrl-D)"),
]

# Copy and paste. Line-by-line mode: the terminal does it (its own keys).
TERMINAL_KEYS = [
    ("drag", "select text (then ctrl+shift+c copies it)"),
    ("ctrl+shift+v", "paste"),
]
# Full-screen app: the app selects (drag to the top or bottom edge to scroll) and copies.
APP_KEYS = [
    ("drag", "select text (drag to the top or bottom edge to scroll)"),
    ("ctrl+c", "copy the selection"),
    ("ctrl+shift+v", "paste from outside the app"),
]
# A terminal app can't read the system clipboard: the terminal sends it on its paste key.
PASTE_TIP = "Paste with ctrl+shift+v (the terminal's paste)"

STATUS_WORDS = {"ok": "verified answer", "rejected": "blocked answer", "max_turns": "unfinished"}

# Pixel-art train, one character per pixel, two pixel rows per terminal line.
# . transparent  B body  S stripe (accent)  W window  D dark (bogies, wheels)  L headlight
# An original design: two trailer cars, couplings, a power car with a long sloped nose.
SPRITE = [
    "..BBBBBBBBBBBBBBBBBBB...BBBBBBBBBBBBBBBBBBB...BBBBBBBBBBBBBBB.............",
    ".BBBBBBBBBBBBBBBBBBBBB.BBBBBBBBBBBBBBBBBBBBB.BBBBBBBBBBBBBBBBBBB..........",
    ".BWWWBWWWBWWWBWWWBWWWB.BWWWBWWWBWWWBWWWBWWWB.BBWWWBWWWBWWWBBBWWWWBB.......",
    ".BWWWBWWWBWWWBWWWBWWWB.BWWWBWWWBWWWBWWWBWWWB.BBWWWBWWWBWWWBBBBWWWWWBB.....",
    ".BBBBBBBBBBBBBBBBBBBBB.BBBBBBBBBBBBBBBBBBBBB.BBBBBBBBBBBBBBBBBBBBBBBBBBB..",
    ".SSSSSSSSSSSSSSSSSSSSS.SSSSSSSSSSSSSSSSSSSSS.SSSSSSSSSSSSSSSSSSSSSSSSSSSLL",
    ".BBBBBBBBBBBBBBBBBBBBBDBBBBBBBBBBBBBBBBBBBBBDBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
    ".BBBBBBBBBBBBBBBBBBBBBDBBBBBBBBBBBBBBBBBBBBBDBBBBBBBBBBBBBBBBBBBBBBBBBBBB.",
    "..DDDDD.......DDDDD.....DDDDD.......DDDDD.....DDDDD.........DDDDD.........",
    "...D.D.........D.D.......D.D.........D.D.......D.D...........D.D..........",
]
# Narrower terminals get fewer cars, so the arrival positions stay far apart.
SPRITE_TWO_CARS = ["." + row[23:] for row in SPRITE]  # one trailer car + power car
SPRITE_SHORT = [row[45:] for row in SPRITE]  # the power car only

# ASCII train, for --plain, NO_COLOR and 8-color terminals (4 lines, 42 columns).
TRAIN_ASCII = [
    " ___________ ___________ _________",
    "|[] [] [] []||[] [] [] []||[] [] []`-.__",
    "|___________||___________||____________ \\",
    "  (o)   (o)    (o)   (o)    (o)    (o)--'",
]
TRAIN_ASCII_SHORT = [
    " ______ ______ _____",
    "|[] []||[] []||[] []`-.",
    " 'o-o'  'o-o'  'o-o'--'",
]

# Thinking spinner: a tiny train moving along a line.
SPINNER_TRACK = 10
SPINNER_FRAMES = ["·" * i + "=>" + "·" * (SPINNER_TRACK - i) for i in range(SPINNER_TRACK + 1)]
FLAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class Arrival(Enum):
    """How the train arrives in the startup banner, from the real startup check."""

    EARLY = "early"
    ON_TIME = "on time"
    LATE = "late"
    CANCELLED = "cancelled"


ARRIVAL_COLORS = {
    Arrival.EARLY: theme.STATUS_EARLY,
    Arrival.ON_TIME: theme.STATUS_ON_TIME,
    Arrival.LATE: theme.STATUS_LATE,
    Arrival.CANCELLED: theme.STATUS_CANCELLED,
}
HEADLIGHT_COLORS = {**ARRIVAL_COLORS, Arrival.CANCELLED: theme.SPRITE_LIGHT_OFF}  # cancelled: light off

# ------------------------------------------------------------ 2. pure functions


def plural(n, singular, plural_form):
    """English plural: 1 takes the singular ("1 step"), everything else the plural ("0 steps")."""
    return singular if abs(n) == 1 else plural_form


def fmt_number(value, percent=False, decimals=None):
    """Display of a number: 41203 -> "41,203", 0.842 (percent) -> "84.2%".

    Only the text changes, never the value. `decimals` fixes the number of
    decimals; by default a percent has 1, other numbers keep their own.
    """
    if percent:
        value = value * 100
        decimals = 1 if decimals is None else decimals
    if decimals is None and isinstance(value, float) and value.is_integer():
        value = int(value)
    text = f"{value:,.{decimals}f}" if decimals is not None else f"{value:,}"
    return text + "%" if percent else text


def fmt_seconds(seconds):
    """A duration: milliseconds under 1 s ("3 ms"), else seconds with 1 decimal ("1.2 s")."""
    if seconds < 1:
        return f"{fmt_number(round(seconds * 1000))} ms"
    return f"{fmt_number(seconds, decimals=1)} s"


def classify_arrival(status):
    """Arrival state from the startup check (thresholds in config.py)."""
    if not (status.server_ok and status.data_ok) or status.latency_s is None:
        return Arrival.CANCELLED
    if status.latency_s < EARLY_S:
        return Arrival.EARLY
    if status.latency_s <= LATE_S:
        return Arrival.ON_TIME
    return Arrival.LATE


def fix_commands(status):
    """The commands that fix a failed startup (empty list if nothing to fix)."""
    commands = []
    if not status.server_ok:
        commands.append(SERVER_FIX_COMMAND)
    if not status.data_ok:
        commands.append(DATA_FIX_COMMAND)
    return commands


def interval_bar(estimate, low, high, width=BAR_WIDTH):
    """Bar "├────●────┤" from low to high, the dot at the estimate's position."""
    if high <= low:
        position = width // 2
    else:
        position = round((estimate - low) / (high - low) * (width - 1))
    position = min(max(position, 0), width - 1)
    return "├" + "─" * position + "●" + "─" * (width - 1 - position) + "┤"


def truncate_lines(text, max_lines):
    """Keep the first max_lines lines. Returns (text, number of hidden lines)."""
    lines = text.splitlines()
    if max_lines is None or len(lines) <= max_lines:
        return text, 0
    return "\n".join(lines[:max_lines]), len(lines) - max_lines


def parse_table(text):
    """Rows of a table printed by pandas (columns separated by 2+ spaces), or None.

    pandas prints the header without a cell for the index, so the header may
    have one cell less than the other rows.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    rows = [re.split(r"\s{2,}", line.strip()) for line in lines]
    width = len(rows[1])
    if width < 2 or any(len(row) != width for row in rows[1:]):
        return None
    if len(rows[0]) == width - 1:
        rows[0] = [""] + rows[0]
    return rows if len(rows[0]) == width else None


def strip_markdown(text):
    """Remove the Markdown bold and code marks the model writes (**9,5 %**, `df`)."""
    return text.replace("**", "").replace("`", "")


def answer_refs(text, sources):
    """The call_ids cited by the answer, in order of first appearance: marker [n] = refs[n-1]."""
    refs = []
    for written in NUMBER_PATTERN.findall(text):
        call_id = sources.get(written)
        if call_id is not None and call_id not in refs:
            refs.append(call_id)
    return refs


def platform_span(width):
    """(first column, column after the last) of the platform on a track `width` wide."""
    end = width - PLATFORM_MARGIN
    return end - PLATFORM_WIDTH, end


def train_x(t, arrival, width, train_width):
    """Column of the train's left end at time t (it starts outside the screen, on the left)."""
    platform_start, platform_end = platform_span(width)
    end = {
        Arrival.EARLY: platform_start - train_width - 1,  # nose stops before the platform
        Arrival.ON_TIME: platform_end - train_width,  # nose exactly at the end of the platform
        Arrival.LATE: platform_end - train_width + LATE_OVERSHOOT,  # slightly past it
        Arrival.CANCELLED: max(width // 2 - train_width, 0),  # stops mid-track, fully visible
    }[arrival]
    progress = min(max(t / TRAIN_ANIM_S, 0.0), 1.0)
    if arrival is Arrival.LATE:
        eased = 1 - (1 - progress) ** 3  # strong slowdown at the end
    elif arrival is Arrival.CANCELLED:
        eased = progress  # constant speed, then an abrupt stop
    else:
        eased = 1 - (1 - progress) ** 2
    start = -train_width
    return round(start + (end - start) * eased)


def flap(text, reveal, rng):
    """Split-flap effect: the first `reveal` share of letters is final, the rest is random."""
    shown = round(len(text) * reveal)
    rest = "".join(c if c == " " else rng.choice(FLAP_CHARS) for c in text[shown:])
    return text[:shown] + rest


# --------------------------------------------------- 3. train drawing and banner


def sprite_palette(headlight):
    """Pixel key -> color (None = transparent). The headlight color shows the arrival state."""
    return {
        ".": None,
        "B": theme.SPRITE_BODY,
        "S": theme.ACCENT,
        "W": theme.SPRITE_WINDOW,
        "D": theme.SPRITE_DARK,
        "L": headlight,
    }


def pixel_pair(top, bottom):
    """One terminal cell for two stacked pixels: (character, style or None).

    "▀" shows the top pixel in the foreground and the bottom pixel in the
    background. Transparent pixels never get a background color, so the
    sprite never paints a rectangle on the terminal.
    """
    if top is None and bottom is None:
        return " ", None
    if bottom is None:
        return "▀", top
    if top is None:
        return "▄", bottom
    return "▀", f"{top} on {bottom}"


def render_sprite(rows, palette):
    """Sprite rows -> terminal lines (one Text per two pixel rows)."""
    lines = []
    for y in range(0, len(rows), 2):
        top_row = rows[y]
        bottom_row = rows[y + 1] if y + 1 < len(rows) else "." * len(top_row)
        line = Text()
        for top_key, bottom_key in zip(top_row, bottom_row):
            char, style = pixel_pair(palette[top_key], palette[bottom_key])
            line.append(char, style=style)
        lines.append(line)
    return lines


def sprite_for_width(width):
    """The sprite that fits the terminal: 3 cars, 2 cars, or the power car alone."""
    if width >= THREE_CARS_WIDTH:
        return SPRITE
    if width >= WIDE_WIDTH:
        return SPRITE_TWO_CARS
    return SPRITE_SHORT


@lru_cache(maxsize=None)
def train_lines(arrival, width, pixels):
    """The train's terminal lines, built once per state and width, then cached (frames only shift them)."""
    if pixels:
        rows = sprite_for_width(width)
        return tuple(render_sprite(rows, sprite_palette(HEADLIGHT_COLORS[arrival])))
    drawing = TRAIN_ASCII_SHORT if width < WIDE_WIDTH else TRAIN_ASCII
    width = max(len(line) for line in drawing)
    return tuple(Text(line.ljust(width)) for line in drawing)


def shift_text(line, x, width):
    """Move a line to column x (negative: partly off screen on the left), cut to `width`."""
    if x >= 0:
        moved = Text(" " * x)
        moved.append_text(line)
    else:
        moved = line[-x:]
    moved.truncate(width)
    return moved


def badge(symbol, label, details, color):
    """The one badge shape: symbol, bold label, "·", details, all in one status color."""
    return Text.assemble(
        (f"{symbol} ", color),
        (label, f"bold {color}"),
        (f" · {details}" if details else "", color),
    )


def arrival_badge(status, progress=1.0):
    """E.g. "● On time · ping 1.2 s". `progress` (0 to 1) grows the delay clock."""
    arrival = classify_arrival(status)
    color = ARRIVAL_COLORS[arrival]
    if arrival is Arrival.CANCELLED:
        reasons = []
        if not status.server_ok:
            reasons.append(f"server unreachable ({status.endpoint})")
        if not status.data_ok:
            reasons.append("clean data missing")
        return badge("✗", "Cancelled", " · ".join(reasons), color)
    latency = fmt_seconds(status.latency_s)
    if arrival is Arrival.LATE:
        extra = (status.latency_s - LATE_S) * progress
        return badge("●", f"Delayed +{fmt_number(extra, decimals=1)} s", f"⏱ ping {latency}", color)
    name = "Early" if arrival is Arrival.EARLY else "On time"
    return badge("●", name, f"ping {latency}", color)


def frame(t, status, width, pixels=False):
    """The startup banner at time t (seconds). frame(TRAIN_ANIM_S, ...) is the final image."""
    arrival = classify_arrival(status)
    width = min(width, SCENE_MAX_WIDTH)
    lines = train_lines(arrival, width, pixels)
    x = train_x(t, arrival, width, lines[0].cell_len)
    platform_start, platform_end = platform_span(width)
    port = status.endpoint.rsplit(":", 1)[-1]

    scene = Text()
    sign = f"▐ TRACK {port} ▌"
    scene.append(" " * max(platform_start + (PLATFORM_WIDTH - len(sign)) // 2, 0))
    scene.append(sign + "\n", style=f"bold {theme.ACCENT}")
    for line in lines:
        scene.append_text(shift_text(line, x, width))
        scene.append("\n")
    scene.append("━" * width + "\n", style=theme.MUTED)
    scene.append(" " * platform_start)
    scene.append("▀" * (platform_end - platform_start), style=theme.ACCENT)

    progress = min(max(t / TRAIN_ANIM_S, 0.0), 1.0)
    fixes = [Text(f"→ To fix: {command}", style=theme.ERROR) for command in fix_commands(status)]
    return Group(scene, Text(), arrival_badge(status, progress), *fixes)


def board_info(status):
    """INFO cell of the model line on the departure board."""
    arrival = classify_arrival(status)
    if arrival is Arrival.LATE:
        return f"delayed +{fmt_number(status.latency_s - LATE_S, decimals=1)} s"
    return arrival.value


def board(status, width, plain=False, reveal=1.0, now=None, seed=0):
    """Departure board with the real startup values. `reveal` < 1 shows the split-flap effect."""
    now = now or datetime.now()
    port = status.endpoint.rsplit(":", 1)[-1]
    if status.data_ok:
        rows_text = f"{fmt_number(status.n_rows)} {plural(status.n_rows, 'row', 'rows')}"
    else:
        rows_text = "missing"
    header = ["DEPARTS", "DESTINATION", "TRACK", "STATUS"]
    rows = [
        [now.strftime("%H:%M"), status.model_name, port, board_info(status)],
        ["DATA", "SNCF TGV punctuality", "—", rows_text],
        ["GUARD", "Numbers checked", "ON" if status.guard_enabled else "OFF", "brick 3"],
    ]
    # Only the STATUS cells carry a status color; everything else is the accent.
    info_colors = [
        ARRIVAL_COLORS[classify_arrival(status)],
        theme.OK if status.data_ok else theme.ERROR,
        theme.OK if status.guard_enabled else theme.ERROR,
    ]
    if width < WIDE_WIDTH:  # narrow terminal: drop the TRACK column
        header.pop(2)
        rows = [row[:2] + row[3:] for row in rows]

    rng = random.Random(seed)
    table = Table(
        box=None if plain else theme.TABLE_BOX,
        header_style=f"bold {theme.ACCENT}",
        border_style=theme.MUTED,
        padding=(0, 1),
    )
    for name in header:
        table.add_column(name, no_wrap=True)
    for row, info_color in zip(rows, info_colors):
        cells = [Text(flap(cell, reveal, rng), style=theme.ACCENT) for cell in row]
        cells[-1].stylize(f"bold {info_color}")
        table.add_row(*cells)
    return table


# ---------------------------------------------------------------- 4. renderers


def panel(body, title, plain, border=theme.MUTED, subtitle=None):
    """The one panel style; in --plain mode a simple title line above the content."""
    if plain:
        heading = f"--- {title} ---" + (f" ({subtitle})" if subtitle else "")
        return Group(Text(heading), body)
    return Panel(
        body,
        title=Text(title, style=f"bold {theme.ACCENT}"),
        title_align="left",
        subtitle=Text(subtitle, style=border) if subtitle else None,
        subtitle_align="left",
        border_style=border,
        box=theme.PANEL_BOX,
        padding=theme.PANEL_PADDING,
    )


def render_tool_call(event, plain=False):
    """Panel "Tool call [n] · run_python" with the code (line numbers)."""
    if event.name == "run_python":
        body = Syntax(
            event.code, "python", line_numbers=True, word_wrap=True,
            theme=theme.SYNTAX_THEME, background_color="default",
        )
    else:
        body = Text(event.code or "(no arguments)")
    return panel(body, f"Tool call [{event.call_id}] · {event.name}", plain)


def render_tool_result(event, plain=False, max_lines=MAX_RESULT_LINES):
    """The tool output: a table if it looks like one, else text. Red border if it failed."""
    text, hidden = truncate_lines(event.output.rstrip("\n"), max_lines)
    rows = parse_table(text)
    if rows:
        body = Table(box=None if plain else theme.TABLE_BOX, border_style=theme.MUTED, show_edge=False)
        for name in rows[0]:
            body.add_column(name, header_style=f"bold {theme.ACCENT}")
        for row in rows[1:]:
            body.add_row(*row)
    else:
        body = Text(text)
    if hidden:
        note = f"… ({hidden} more {plural(hidden, 'line', 'lines')}, /trace to see everything)"
        body = Group(body, Text(note, style=theme.MUTED))
    title = f"Result [{event.call_id}]"
    if event.error:
        return panel(body, title + " · error", plain, border=theme.ERROR, subtitle=event.error)
    return panel(body, title, plain)


def render_guard(event):
    """Brick 3 badge: ✓ verified, ✗ blocked, or ○ when there was no number to check."""
    if event.passed and not event.checked:
        return badge("○", "GUARD", "no number to check", theme.MUTED)
    if event.passed:
        n = len(event.checked)
        return badge("✓", "GUARD", f"{n} {plural(n, 'number', 'numbers')} verified", theme.OK)
    numbers = ", ".join(event.rejected)
    lines = [badge("✗", "GUARD · BLOCKED", f"{numbers} never computed", theme.ERROR)]
    if event.will_retry:
        lines.append(Text("  → Qwen gets this list and must fix its answer (2nd try)", style=theme.MUTED))
    return Group(*lines)


def render_answer(event, plain=False):
    """Panel "Answer": each number with a source is highlighted and followed by [n].

    Only answers accepted by the guard are shown, so the border takes the OK color.
    """
    text = strip_markdown(event.text)
    refs = answer_refs(text, event.sources)
    answer = Text()
    position = 0
    for match in NUMBER_PATTERN.finditer(text):
        call_id = event.sources.get(match.group())
        if call_id is None:
            continue
        answer.append(text[position:match.start()])
        answer.append(match.group(), style=f"bold {theme.ACCENT}")
        answer.append(f"[{refs.index(call_id) + 1}]", style=theme.MUTED)
        position = match.end()
    answer.append(text[position:])
    return panel(answer, "Answer", plain, border=theme.OK)


def render_sources(event):
    """Muted line under the answer: "Sources: [1] call 1 · [2] call 3"."""
    refs = answer_refs(strip_markdown(event.text), event.sources)
    if not refs:
        return Text("Sources: no computed number in the answer", style=theme.MUTED)
    parts = [f"[{i}] call {call_id}" for i, call_id in enumerate(refs, start=1)]
    return Text("Sources: " + " · ".join(parts), style=theme.MUTED)


def render_interval(event):
    """One line: "640 / 6704  9.5%  ├────●────┤  [8.9, 10.3]  95% CI"."""
    low = fmt_number(event.low * 100, decimals=1)
    high = fmt_number(event.high * 100, decimals=1)
    level = fmt_number(event.level, percent=True, decimals=0)
    return Text.assemble(
        (f"{event.label}  ", "bold"),
        (fmt_number(event.estimate, percent=True), f"bold {theme.ACCENT}"),
        "  ",
        (interval_bar(event.estimate, event.low, event.high), theme.MUTED),
        f"  [{low}, {high}]  ",
        (f"{level} CI", theme.MUTED),
    )


def render_reasoning(event, plain=False):
    """The model's reasoning for one turn, in muted text."""
    return panel(Text(event.text.strip(), style=theme.MUTED), f"Reasoning · step {event.step}", plain)


def render_log(rows):
    """data/cleaning_log.csv as a table. `rows` = list of lists, header first."""
    table = Table(
        title=Text("Cleaning log", style=f"bold {theme.ACCENT}"), title_justify="left",
        box=theme.TABLE_BOX, border_style=theme.MUTED, header_style=f"bold {theme.ACCENT}",
    )
    table.add_column("Step")
    table.add_column("Rule")
    table.add_column("Rows affected", justify="right")
    for step, rule, count in rows[1:]:
        table.add_row(step, rule, fmt_number(int(count)) if count.isdigit() else count)
    return table


def render_help(keys=TERMINAL_KEYS):
    """Table of the commands, then the copy and paste keys (the app passes APP_KEYS)."""
    table = Table(box=None, show_header=False, padding=(0, 2))
    for command, meaning in COMMANDS:
        table.add_row(Text(command, style=f"bold {theme.ACCENT}"), meaning)
    for keys, meaning in keys:
        table.add_row(Text(keys, style=theme.MUTED), meaning)
    return table


def render_summary(result):
    """Line after a question: status word in its color, then steps, time and tokens."""
    trace = result["trace"]
    color = theme.OK if result["status"] == "ok" else theme.ERROR
    turns, tokens = trace["turns"], trace["tokens"]
    return Text.assemble(
        (STATUS_WORDS.get(result["status"], result["status"]), f"bold {color}"),
        (
            f" · {turns} {plural(turns, 'step', 'steps')}"
            f" · {fmt_number(trace['seconds'], decimals=1)} s"
            f" · {fmt_number(tokens)} {plural(tokens, 'token', 'tokens')}",
            theme.MUTED,
        ),
    )


def render_result(result):
    """End of a question: the reason when there is no answer, then the summary line."""
    trace = result["trace"]
    lines = []
    if result["status"] == "rejected":
        unsupported = trace["unsupported"]
        numbers = ", ".join(unsupported)
        lines.append(Text(f"Answer blocked by the guard: {numbers} never computed by code.", style=theme.ERROR))
    elif result["status"] == "max_turns":
        turns = trace["turns"]
        message = f"No answer in {turns} {plural(turns, 'step', 'steps')}. Try a simpler question."
        lines.append(Text(message, style=theme.ERROR))
    lines.append(render_summary(result))
    return Group(*lines)


class TrainSpinner:
    """Spinner shown while the model thinks; rich redraws it about 10 times per second."""

    def __init__(self, step):
        self.step = step
        self.start = time.monotonic()

    def __rich__(self):
        elapsed = time.monotonic() - self.start
        train = SPINNER_FRAMES[int(elapsed * SPINNER_FPS) % len(SPINNER_FRAMES)]
        return Text.assemble(
            (train, theme.ACCENT),
            (f"  Qwen is thinking… step {self.step} · {int(elapsed)} s", theme.MUTED),
        )


# ------------------------------------------------------------------ 5. Display


def to_text(renderable, width):
    """Draw any rich renderable (panel, table, group...) as styled Text, `width` columns wide.

    The full-screen app shows its history as Text because Textual can only select
    text with the mouse, not panels or tables. Colors and borders stay the same.
    """
    console = Console(width=width, force_terminal=True, color_system="truecolor",
                      highlight=False, file=io.StringIO())
    lines = console.render_lines(renderable, console.options.update_width(width), pad=False)
    text = Text(no_wrap=True, overflow="crop", end="")
    for number, line in enumerate(lines):
        for segment in line:
            if not segment.control:
                text.append(segment.text, segment.style)
        if number < len(lines) - 1:
            text.append("\n")
    return text


def make_console(plain=False, **options):
    """The rich Console. --plain and NO_COLOR: no ANSI codes at all (no colors, no bold)."""
    if plain or os.environ.get("NO_COLOR"):
        return Console(color_system=None, highlight=False, **options)
    return Console(highlight=False, **options)


class Display:
    """Prints the renderers. Its `on_event` method is the callback given to the agent."""

    def __init__(self, console=None, plain=False, animate=True, show_thinking=False):
        self.console = console or make_console(plain)
        self.plain = plain
        self.live = not plain and self.console.is_terminal  # spinner and animations possible
        self.animate = animate and self.live and self.console.width >= MIN_ANIM_WIDTH
        # Half-block pixels need real colors: ASCII train for --plain, NO_COLOR and 8 colors.
        self.pixels = (
            not plain
            and not self.console.no_color
            and self.console.color_system not in (None, "standard")
        )
        self.show_thinking = show_thinking
        self.events = []  # events of the last question, for /trace
        self.spinner = None

    def block(self, renderable):
        """Print one block followed by a blank line, so no block touches the next one."""
        self.console.print(renderable)
        self.console.print()

    # --- startup

    def checking(self):
        """Context shown while agent.check_startup() runs (the ping can take a few seconds)."""
        if self.live:
            return self.console.status("Checking the server and the data…", spinner_style=theme.ACCENT)
        return nullcontext()

    def show_startup(self, status, think):
        """Banner (train + departure board), animated if possible."""
        width = self.console.width
        for _ in range(TOP_MARGIN):
            self.console.print()
        if self.animate:
            self.play(lambda t: frame(t, status, width, self.pixels), TRAIN_ANIM_S)
            self.console.print()
            self.play(lambda t: board(status, width, reveal=t / FLAP_ANIM_S, seed=int(t * FPS)), FLAP_ANIM_S)
            self.console.print()
        else:
            self.block(frame(TRAIN_ANIM_S, status, width, self.pixels))
            self.block(board(status, width, plain=self.plain))
        mode = "on" if think else "off"
        self.block(Text(f"Model thinking: {mode} · /help for the commands", style=theme.MUTED))
        self.block(Text(DATA_LIMITS, style=f"italic {theme.MUTED}"))

    def show_status(self, status):
        """/status: the board and the arrival badge again, without animation."""
        self.block(board(status, self.console.width, plain=self.plain))
        lines = [arrival_badge(status)]
        lines += [Text(f"→ To fix: {command}", style=theme.ERROR) for command in fix_commands(status)]
        self.block(Group(*lines))

    def play(self, draw, duration):
        """Animation loop: draw(t) for t from 0 to duration, at FPS frames per second."""
        n_frames = max(1, round(duration * FPS))
        with Live(draw(0.0), console=self.console, refresh_per_second=FPS, auto_refresh=False) as live:
            for i in range(1, n_frames + 1):
                time.sleep(1 / FPS)  # the only sleep in this file
                live.update(draw(duration * i / n_frames), refresh=True)

    # --- one question

    def start_question(self):
        """Forget the previous question's events (/trace shows only the last one)."""
        self.events = []
        self.console.print()

    def on_event(self, event):
        """Callback for agent.run_agent: keep the event for /trace and draw it."""
        self.events.append(event)
        self.stop_spinner()
        if isinstance(event, Thinking):
            self.start_spinner(event.step)
        else:
            self.render(event)

    def render(self, event, full=False):
        """Print one event. full=True (/trace): no cut, reasoning always shown."""
        if isinstance(event, Thinking):
            self.block(Text(f"— Step {event.step}: Qwen is thinking —", style=theme.MUTED))
        elif isinstance(event, Reasoning):
            if self.show_thinking or full:
                self.block(render_reasoning(event, self.plain))
        elif isinstance(event, ToolCall):
            self.block(render_tool_call(event, self.plain))
        elif isinstance(event, ToolResult):
            self.block(render_tool_result(event, self.plain, None if full else MAX_RESULT_LINES))
        elif isinstance(event, ConfidenceInterval):
            self.block(render_interval(event))
        elif isinstance(event, GuardVerdict):
            self.block(render_guard(event))
        elif isinstance(event, FinalAnswer):
            self.console.print(render_answer(event, self.plain))
            self.block(render_sources(event))

    def start_spinner(self, step):
        """Train spinner while the model thinks (a simple line if no live terminal)."""
        if not self.live:
            self.block(Text(f"Qwen is thinking… (step {step})", style=theme.MUTED))
            return
        self.spinner = Live(TrainSpinner(step), console=self.console, refresh_per_second=SPINNER_FPS, transient=True)
        self.spinner.start()

    def stop_spinner(self):
        """Stop the spinner, if one is running."""
        if self.spinner:
            self.spinner.stop()
            self.spinner = None

    def show_result(self, result):
        """After the question: why there is no answer (if so), then the summary line."""
        self.block(render_result(result))

    # --- REPL helpers

    def read_question(self):
        """Read the user's question, typed inside a full-width box (simple prompt if no live terminal).

        A line ending with \\ continues on a new line: the box grows by one line.
        """
        if not self.live:
            return self.console.input(PLAIN_PROMPT)
        lines = []
        while True:
            self.draw_question_box(lines)
            # Below the box: the hint, the bottom border, then the empty line to type on.
            self.write(CURSOR_UP.format(3) + "\r" + CURSOR_RIGHT.format(2 + len(PROMPT_MARK)))
            try:
                line = input()
            except (KeyboardInterrupt, EOFError):
                self.write(CURSOR_DOWN.format(3) + "\r")  # still on the typing line: go below the hint
                raise
            if not line.endswith(NEW_LINE_KEY):
                self.write(CURSOR_DOWN.format(2) + "\r")  # Enter put us on the bottom border
                self.console.print()
                return "\n".join(lines + [line])
            lines.append(line[: -len(NEW_LINE_KEY)])
            # Enter put us on the bottom border: go back to the top border and erase the box.
            self.write(CURSOR_UP.format(len(lines) + 1) + "\r" + CLEAR_TO_END)

    def draw_question_box(self, lines):
        """The question box, as wide as the terminal: the lines already typed,
        an empty line to type on, then the hint below the box."""
        inner = self.console.width - 2
        border = theme.MUTED
        self.console.print(Text("╭" + "─" * inner + "╮", style=border))
        for i, text in enumerate(lines + [""]):
            mark = PROMPT_MARK if i == 0 else CONTINUE_MARK
            row = Text.assemble(("│ ", border), (mark, f"bold {theme.ACCENT}"), text)
            row.append(" " * max(inner - 1 - len(mark) - len(text), 0))
            row.append("│", style=border)
            self.console.print(row)
        self.console.print(Text("╰" + "─" * inner + "╯", style=border))
        self.console.print(Text("  " + PROMPT_HINT, style=theme.MUTED), overflow="ellipsis", no_wrap=True)

    def write(self, codes):
        """Send cursor moves straight to the terminal."""
        self.console.file.write(codes)
        self.console.file.flush()

    def show_trace(self):
        """/trace: every event of the last question, without cuts."""
        if not self.events:
            self.block("No question yet.")
        for event in self.events:
            self.render(event, full=True)

    def show_help(self):
        self.block(render_help())

    def show_log(self, rows):
        self.block(render_log(rows))

    def show_error(self, text):
        self.block(Text(text, style=theme.ERROR))

    def show_goodbye(self):
        self.console.print("Goodbye 👋")


# ------------------------------------------------------------------ 6. preview


def sample_status(latency, server_ok=True, data_ok=True):
    """A made-up StartupStatus for the preview (real values come from agent.check_startup)."""
    return StartupStatus(
        server_ok=server_ok, latency_s=latency if server_ok else None, data_ok=data_ok,
        n_rows=12792 if data_ok else None, model_name="qwen3.5-4b-16k",
        endpoint="localhost:11434", guard_enabled=True,
    )


SAMPLE_CODE = (
    "route = df[(df['gare_depart'] == 'PARIS LYON') & (df['year'] == 2024)]\n"
    "print(route['nb_circules'].sum(), route['nb_train_retard_arrivee'].sum())"
)


def preview(console=None):
    """Print every look of the CLI with sample values, without animation and without the model."""
    display = Display(console=console, animate=False)
    note = "Preview with sample values: nothing here comes from the model."
    display.block(Text(note, style=theme.MUTED))
    for latency, server_ok in [(0.004, True), (1.2, True), (5.4, True), (None, False)]:
        status = sample_status(latency, server_ok=server_ok)
        display.block(Text(f"State: {classify_arrival(status).value}", style=f"bold {theme.ACCENT}"))
        display.show_startup(status, think=True)

    display.block(Text("Question with a passed guard", style=f"bold {theme.ACCENT}"))
    for event in [
        ToolCall(call_id=1, code=SAMPLE_CODE),
        ToolResult(call_id=1, output="6704 640\n", numbers=[6704.0, 640.0]),
        ToolCall(call_id=2, code='{"late": 640, "total": 6704}', name="confidence_interval"),
        ToolResult(call_id=2, output="rate: 0.0955 (9.5 %)\n95% confidence interval: [0.0886, 0.1028] ([8.9 %, 10.3 %])"),
        ConfidenceInterval(label="640 / 6704", estimate=640 / 6704, low=0.0886, high=0.1028),
        GuardVerdict(passed=True, checked=["6704", "640", "9.5", "8.9", "10.3"], rejected=[]),
        FinalAnswer(
            text="In 2024, 640 of 6704 trains arrived late, so 9.5% (95% CI: 8.9 to 10.3%).",
            sources={"640": 1, "6704": 1, "9.5": 2, "8.9": 2, "10.3": 2},
        ),
    ]:
        display.render(event)
    display.show_result({"status": "ok", "trace": {"turns": 3, "seconds": 41.2, "tokens": 9876}})

    display.block(Text("Question with a blocked guard", style=f"bold {theme.ACCENT}"))
    error = "NameError: name 'confidence_interval' is not defined"
    display.render(ToolCall(call_id=1, code="print(confidence_interval(640, 6704))"))
    display.render(ToolResult(call_id=1, output=f"Error:\n{error}", error=error))
    display.render(GuardVerdict(passed=False, checked=["87.3", "640"], rejected=["87.3"], will_retry=True))
    display.render(GuardVerdict(passed=False, checked=["87.3"], rejected=["87.3"]))
    blocked = {"turns": 4, "seconds": 52.3, "tokens": 14210, "unsupported": ["87.3"]}
    display.show_result({"status": "rejected", "trace": blocked})

    display.block(Text("Message with no number (\"hello\")", style=f"bold {theme.ACCENT}"))
    display.render(GuardVerdict(passed=True, checked=[], rejected=[]))
    display.render(FinalAnswer(text="Hello! Ask me a question about TGV punctuality.", sources={}))
    display.show_result({"status": "ok", "trace": {"turns": 1, "seconds": 4.5, "tokens": 2034}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show the CLI's look with sample values.")
    parser.add_argument("--preview", action="store_true", help="print every banner state and sample answers")
    if parser.parse_args().preview:
        preview()
    else:
        parser.print_help()
