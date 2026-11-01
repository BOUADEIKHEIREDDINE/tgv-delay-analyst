"""Run the CLI without installing it: `python main.py` (same as the `tgv` command)."""

import sys
from pathlib import Path

# The package is in src/: make it importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tgv_analyst.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
