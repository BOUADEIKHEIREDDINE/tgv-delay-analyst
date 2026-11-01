"""Download the SNCF TGV monthly punctuality dataset into data/raw/."""

from pathlib import Path
from urllib.request import urlretrieve

URL = (
    "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/"
    "regularite-mensuelle-tgv-aqst/exports/csv?delimiter=%3B"
)

# Paths are relative to the project root, so the script works from any folder.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_FILE = RAW_DIR / "regularite-mensuelle-tgv-aqst.csv"


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {URL}")
    urlretrieve(URL, OUTPUT_FILE)
    print(f"Saved to {OUTPUT_FILE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
