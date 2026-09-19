"""Fetch the UCI Bank Marketing dataset, and record which variant was taken.

    python scripts/download_bank_data.py

Writes data/bank/bank-additional-full.csv and data/bank/dataset.json.

The archive contains four CSVs, and the choice between them matters more than it looks.
`bank-full.csv` has 45,211 rows and 16 inputs. `bank-additional-full.csv` has 41,188 rows
and 20, and the four extra columns are macroeconomic indicators recorded at the time of each
call: the three-month Euribor rate, employment variation, consumer price and confidence
indices, and the number employed.

Those columns are why this project uses the second file. The campaign ran from May 2008 to
November 2010, straight through the financial crisis, and the rows are stored in time order.
The Euribor rate falls from 4.86 to 0.80 across the file and the subscription rate rises
with it. That is a real distribution shift in a public dataset, which most tabular
benchmarks do not have, and it is the difference between a monitoring story that is measured
and one that is simulated.

The file is also a snapshot that never changes, so it is downloaded once and versioned with
DVC rather than fetched at training time.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BANK_DIR = PROJECT_ROOT / "data" / "bank"

ARCHIVE_URL = "https://archive.ics.uci.edu/static/public/222/bank+marketing.zip"

# The path inside the nested archive, and the name we store it under.
WANTED_MEMBER = "bank-additional/bank-additional-full.csv"
OUTPUT_NAME = "bank-additional-full.csv"

CITATION = (
    "Moro, S., Rita, P., and Cortez, P. (2014). Bank Marketing [Dataset]. "
    "UCI Machine Learning Repository. https://doi.org/10.24432/C5K306"
)
LICENCE = "CC BY 4.0"


def parse_command_line() -> argparse.Namespace:
    """Command line for the dataset download."""
    parser = argparse.ArgumentParser(description="Download the Bank Marketing dataset")
    parser.add_argument("--out-dir", type=Path, default=BANK_DIR)
    parser.add_argument("--force", action="store_true",
                        help="download again even if the file is already present")
    return parser.parse_args()


def extract_wanted_csv(archive_bytes: bytes) -> bytes:
    """Pull the one CSV we want out of the nested archive.

    The download is a zip containing two zips. Rather than unpacking everything to disk and
    picking through it, this reaches for the single member by name, so a change in the
    archive's shape fails loudly here instead of silently selecting a different file.
    """
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as outer:
        inner_names = [name for name in outer.namelist()
                       if name.endswith("bank-additional.zip")]
        if not inner_names:
            raise SystemExit(
                f"bank-additional.zip is not in the archive. It now contains: "
                f"{outer.namelist()}"
            )
        inner_bytes = outer.read(inner_names[0])

    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        matches = [name for name in inner.namelist() if name.endswith(WANTED_MEMBER)]
        if not matches:
            raise SystemExit(
                f"{WANTED_MEMBER} is not in the inner archive, which contains: "
                f"{inner.namelist()}"
            )
        return inner.read(matches[0])


def main() -> int:
    """Download the archive, extract the chosen CSV, and record what was taken."""
    options = parse_command_line()
    options.out_dir.mkdir(parents=True, exist_ok=True)
    destination = options.out_dir / OUTPUT_NAME

    if destination.exists() and not options.force:
        print(f"{destination} already exists; pass --force to download again")
        return 0

    print(f"downloading {ARCHIVE_URL}", flush=True)
    response = requests.get(ARCHIVE_URL, timeout=120)
    if not response.ok:
        raise SystemExit(f"download failed with HTTP {response.status_code}")

    csv_bytes = extract_wanted_csv(response.content)
    destination.write_bytes(csv_bytes)

    row_count = csv_bytes.count(b"\n") - 1  # the header is not a row
    fingerprint = hashlib.sha256(csv_bytes).hexdigest()

    metadata = {
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": ARCHIVE_URL,
        "file": OUTPUT_NAME,
        "variant": "bank-additional-full",
        "rows": row_count,
        "sha256": fingerprint,
        "licence": LICENCE,
        "citation": CITATION,
        "why_this_variant": (
            "It carries the macroeconomic columns recorded at call time. The campaign ran "
            "May 2008 to November 2010 in time order, so those columns contain a real "
            "distribution shift rather than a simulated one."
        ),
    }
    (options.out_dir / "dataset.json").write_text(
        json.dumps(metadata, indent=2)
    )

    print(f"wrote {destination}  ({row_count:,} rows)")
    print(f"sha256 {fingerprint}")
    print(f"licence {LICENCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
