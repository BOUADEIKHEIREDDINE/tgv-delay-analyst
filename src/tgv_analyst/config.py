"""Project settings: file paths."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLEAN_CSV = PROJECT_ROOT / "data" / "clean" / "tgv_clean.csv"
