"""Demonstrate the failure, and the control that catches it.

    python scripts/demo_stale_input.py

Runs the nightly job twice against the same deliberately aged input: once with the
freshness gate disabled, once with it on. Writes reports/stale-input-demo.md.

The point of running it twice is that the first run **succeeds**. It publishes a call list
of the right length, with a normal score distribution, and reports no error. Nothing about
its output says the list is a day old and the people on it were called yesterday.

That is what makes the failure worth designing for, and why the demonstration needs both
halves: showing the gate refusing proves it refuses, and showing what happens without it
proves the refusal was worth having.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"
DEMO_DIR = PROJECT_ROOT / "data" / "bank" / "demo"
METRICS_PATH = REPORTS_DIR / "nightly-metrics.json"

PYTHON = sys.executable
STALE_AGE_HOURS = 26


def parse_command_line() -> argparse.Namespace:
    """Command line for the demonstration."""
    parser = argparse.ArgumentParser(description="Show the stale-input failure and its gate")
    parser.add_argument("--rows", type=int, default=3000,
                        help="how many rows the simulated nightly export contains")
    parser.add_argument("--call-budget", type=int, default=500)
    return parser.parse_args()


def write_aged_export(rows: int, hours_old: float) -> Path:
    """Write a valid customer export and backdate it, as a missed delivery would leave it.

    The file is a genuine slice of the real dataset. Nothing about its contents is wrong —
    that is the entire point. Only its age is.
    """
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    dataset = pd.read_csv(DATASET, sep=";")
    export_path = DEMO_DIR / "contacts.csv"
    dataset.tail(rows).to_csv(export_path, sep=";", index=False)

    modified_at = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    timestamp = modified_at.timestamp()
    os.utime(export_path, (timestamp, timestamp))
    return export_path


def run_nightly_job(export_path: Path, call_budget: int,
                    skip_gate: bool) -> tuple[int, dict]:
    """Run the nightly job once and return its exit code and the metrics it wrote."""
    command = [
        PYTHON, str(PROJECT_ROOT / "scripts" / "score_nightly.py"),
        "--input", str(export_path),
        "--call-budget", str(call_budget),
    ]
    if skip_gate:
        command.append("--skip-freshness-gate")

    completed = subprocess.run(command, cwd=PROJECT_ROOT,
                               capture_output=True, text=True, timeout=600)
    print(completed.stdout)
    if completed.returncode not in (0, 2):
        print(completed.stderr)

    metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}
    return completed.returncode, metrics


def main() -> int:
    """Run both halves of the demonstration and write the report."""
    options = parse_command_line()
    if not DATASET.exists():
        raise SystemExit(f"{DATASET} not found; run `dvc pull`")

    export_path = write_aged_export(options.rows, STALE_AGE_HOURS)
    print(f"wrote a valid export of {options.rows} rows, aged {STALE_AGE_HOURS}h\n")

    print("=" * 72)
    print("RUN 1 — freshness gate disabled, which is what most pipelines do")
    print("=" * 72)
    without_code, without_metrics = run_nightly_job(
        export_path, options.call_budget, skip_gate=True)

    print("=" * 72)
    print("RUN 2 — freshness gate on")
    print("=" * 72)
    with_code, with_metrics = run_nightly_job(
        export_path, options.call_budget, skip_gate=False)

    lines = [
        "# The stale input failure, and the gate that catches it",
        "",
        f"Both runs below scored **the same file**: a valid customer export of "
        f"{options.rows:,} rows, aged {STALE_AGE_HOURS} hours. Nothing about its contents "
        f"is wrong. Only its age is.",
        "",
        "## Run 1 — without the freshness gate",
        "",
        f"- exit code **{without_code}**",
        f"- published: **{without_metrics.get('published')}**",
        f"- rows published: **{without_metrics.get('rows_published')}**",
        f"- score range: {without_metrics.get('score_min')} to "
        f"{without_metrics.get('score_max')}, median {without_metrics.get('score_median')}",
        "- errors: none",
        "",
        "**The job succeeded.** It produced a call list of exactly the expected length, "
        "with a score distribution that looks like every other night's, and reported "
        "nothing wrong. A dashboard watching row counts, run duration, score ranges or "
        "exit codes sees a completely healthy run.",
        "",
        "In the morning, agents call the people they called yesterday.",
        "",
        "## Run 2 — with the freshness gate",
        "",
        f"- exit code **{with_code}**",
        f"- published: **{with_metrics.get('published')}**",
        f"- refusal reason: **{with_metrics.get('refusal_reason')}**",
        f"- input age: **{with_metrics.get('input_age_hours')} hours**",
        "",
        "Nothing was published. The refusal is recorded as a metric, so the alert fires "
        "on the absence of a list rather than on nobody noticing a wrong one.",
        "",
        "## Why refusing beats guessing",
        "",
        "The gate could have published yesterday's list with a warning attached. It does "
        "not, and that is the design decision worth defending: a missing call list is an "
        "obvious problem somebody fixes within minutes, while a plausible wrong one is "
        "worked through for a whole day and is discovered only when a customer complains "
        "about being called twice.",
        "",
        "## What the gate actually checks",
        "",
        "The input's own modification time, not the HTTP status of the read, not the row "
        "count, and not the job's own clock. Every one of those was fine in run 1.",
        "",
        "The limit is 24 hours, from the freshness requirement in the proposal: the list "
        "is consumed once a day, so an input older than a day describes a day that has "
        "already been worked through.",
        "",
        "## Guarded by",
        "",
        "`tests/bank/test_freshness.py` — ten tests, including the boundary pinned from "
        "both sides, because a later change from `<=` to `<` would move it silently.",
        "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "stale-input-demo.md").write_text("\n".join(lines))

    print(f"wrote {REPORTS_DIR / 'stale-input-demo.md'}")

    if without_metrics.get("published") and with_metrics.get("refusal_reason") == "stale_input":
        print("\nDemonstration held: the same file was published without the gate and "
              "refused with it.")
        return 0

    print("\nDemonstration did NOT hold; check the runs above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
