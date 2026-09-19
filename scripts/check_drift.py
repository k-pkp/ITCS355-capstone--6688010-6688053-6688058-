"""Score drift between the training window and a recent window.

    python scripts/check_drift.py

Writes reports/bank-drift.md. Exits non-zero when any column crosses the alert threshold,
so the scheduled run can be wired to an alert.

The reference window is the training period. The current window is the held-out final
period, which is where the financial crisis sits — so this run is expected to alert, and a
run that did not would mean the detector was broken rather than that the world was calm.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bank import monitoring, splits

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"
REPORT_PATH = PROJECT_ROOT / "reports" / "bank-drift.md"

WATCHED_COLUMNS = (
    "euribor3m", "emp.var.rate", "nr.employed",
    "cons.price.idx", "cons.conf.idx", "age", "campaign",
)


def parse_command_line() -> argparse.Namespace:
    """Command line for the drift check."""
    parser = argparse.ArgumentParser(description="Score drift against the training window")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    parser.add_argument("--exit-zero-on-alert", action="store_true",
                        help="exit 0 even when drift is found. Use on a schedule, where "
                             "the alert is delivered by the monitoring policy and a "
                             "non-zero exit makes a successful detection look like a "
                             "broken job.")
    return parser.parse_args()


def main() -> int:
    """Score every watched column and write the report."""
    options = parse_command_line()
    if not options.dataset.exists():
        raise SystemExit(f"{options.dataset} not found; run `dvc pull`")

    dataset = pd.read_csv(options.dataset, sep=";")
    split = splits.split_by_time(dataset)
    scores = monitoring.score_drift(split.train, split.test, WATCHED_COLUMNS)

    for score in scores:
        print(f"  {score}")

    alerting = [score for score in scores if score.alerts]

    lines = [
        "# Drift report",
        "",
        f"Reference: the training window, {len(split.train):,} rows. "
        f"Current: the held-out final period, {len(split.test):,} rows.",
        "",
        "| Column | PSI | Verdict |",
        "|---|--:|---|",
    ]
    for score in scores:
        lines.append(f"| `{score.column}` | {score.psi:.4f} | "
                     f"{'**ALERT**' if score.alerts else 'stable'} |")

    lines += [
        "",
        f"Threshold {monitoring.PSI_ALERT_THRESHOLD}, carried over from Lab 4 where it was "
        f"set by measuring an unchanged window against the reference.",
        "",
        "## What this is detecting",
        "",
        "The campaign ran May 2008 to November 2010, through the financial crisis. The "
        "macroeconomic columns are not noise here: they record the conditions the calls "
        "were made in, and those conditions changed completely. The subscription rate "
        f"moves from {splits.subscribe_rate(split.train):.1%} in the training window to "
        f"{splits.subscribe_rate(split.test):.1%} in the current one.",
        "",
        "**This run is expected to alert.** A drift check that found nothing here would "
        "mean the detector was broken, not that the world was calm.",
        "",
        "## The limit of this measure",
        "",
        "PSI measures how far the input moved, not how much the model minds. Measured in "
        "Lab 4 on the same detector: a shift scoring 0.383 cost 0.0100 ROC AUC, while one "
        "scoring 0.2627 cost 0.0167 — the larger PSI did the smaller damage. So a PSI "
        "alert opens an investigation and does not rank incidents.",
        "",
    ]
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text("\n".join(lines))

    print(f"\n{len(alerting)} of {len(scores)} columns above the threshold")
    print(f"wrote {options.out}")

    if alerting and not options.exit_zero_on_alert:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
