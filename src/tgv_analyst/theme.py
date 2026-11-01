"""The look of the CLI: every color and box style used by ui.py is defined here.

Colors are named by their role, not by their hue, so a change here changes
the whole screen consistently. The default text color is the terminal's own
(no TEXT color is set), and no background color is used except to draw the
pixels of the train sprite.
"""

from rich import box

# Identity color: train stripe, board text, panel titles, VOIE sign, prompt.
ACCENT = "#f2b84b"  # warm amber, like a station board
# Meta lines: sources, timings, hints, the track, panel borders.
MUTED = "#8b929c"

# Status colors: only for things that carry a status
# (arrival badge, board INFO cell, guard badge, error border, answer border).
STATUS_EARLY = "#4ea8ff"
STATUS_ON_TIME = "#3fbf74"
STATUS_LATE = "#ff7a3d"
STATUS_CANCELLED = "#ef4b4b"
OK = STATUS_ON_TIME
ERROR = STATUS_CANCELLED

# Train sprite pixels (neutral greys: no real railway livery).
SPRITE_BODY = "#dfe3e8"
SPRITE_WINDOW = "#34404e"
SPRITE_DARK = "#22262b"
SPRITE_LIGHT_OFF = "#4a4f57"  # headlight of a cancelled train

# One panel style and one table style for the whole CLI.
PANEL_BOX = box.ROUNDED
PANEL_PADDING = (0, 1)
TABLE_BOX = box.SIMPLE_HEAD
SYNTAX_THEME = "ansi_dark"  # uses the terminal's own 16 colors for code
