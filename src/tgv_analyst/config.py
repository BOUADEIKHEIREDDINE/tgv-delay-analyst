"""Project settings: file paths and startup thresholds."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLEAN_CSV = PROJECT_ROOT / "data" / "clean" / "tgv_clean.csv"
CLEANING_LOG = PROJECT_ROOT / "data" / "cleaning_log.csv"

# Startup check (agent.check_startup, ui.classify_arrival): server ping time in seconds.
EARLY_S = 0.5  # faster than this: the train arrives early
LATE_S = 3.0  # slower than this: the train is late
PING_TIMEOUT_S = 10  # no answer after this: the server counts as unreachable

# Saved conversations of the full-screen app (one JSON file each, gitignored).
CONVERSATIONS_DIR = PROJECT_ROOT / "conversations"
