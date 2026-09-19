"""The nightly job: read tomorrow's contact list, rank it, publish it.

    python scripts/score_nightly.py --input data/bank/incoming/contacts.csv

This is what Cloud Scheduler runs. Six steps, about a minute:

    read input -> FRESHNESS GATE -> data contract -> features -> score -> publish

The gate is second on purpose. Checking freshness before the contract means a stale file is
refused for being stale rather than passing every structural check and then being scored,
and it means the cheapest check runs first.

On a stale input the job publishes nothing, emits the refusal as a metric, and exits
non-zero. That is the designed behaviour, not an error path: a missing call list is noticed
within minutes, and a plausible wrong one is worked through for a day.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bank import contract, features, freshness

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
OUTPUT_DIR = PROJECT_ROOT / "data" / "bank" / "call-lists"
METRICS_PATH = REPORTS_DIR / "nightly-metrics.json"
DEFAULT_MODEL = REPORTS_DIR / "bank-model.joblib"


def parse_command_line() -> argparse.Namespace:
    """Command line for the nightly scoring job."""
    parser = argparse.ArgumentParser(description="Score and rank tomorrow's contact list")
    parser.add_argument("--input", type=Path, required=True,
                        help="the customer export to score")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--call-budget", type=int, default=500,
                        help="how many customers the agents expect to reach")
    parser.add_argument("--now", default=None,
                        help="override the current time, ISO 8601, for replaying a run")
    parser.add_argument("--skip-freshness-gate", action="store_true",
                        help="score the input however old it is. This exists only to "
                             "demonstrate what the gate prevents, and should never be "
                             "used on a scheduled run.")
    return parser.parse_args()


def write_metrics(metrics: dict) -> None:
    """Record one run's metrics where the dashboard reads them."""
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))


def main() -> int:
    """Run the nightly job, publishing a list only if every gate allows it."""
    options = parse_command_line()
    started_at = datetime.now(timezone.utc)
    now = datetime.fromisoformat(options.now) if options.now else started_at

    metrics: dict = {
        "run_at_utc": started_at.isoformat(),
        "input": str(options.input),
        "published": False,
        "refusal_reason": None,
    }

    if not options.input.exists():
        metrics["refusal_reason"] = "input_missing"
        write_metrics(metrics)
        print(f"input {options.input} does not exist; published nothing")
        return 1

    # --- the freshness gate ------------------------------------------------------------
    decision = freshness.check(options.input, now=now)
    metrics["input_age_hours"] = round(decision.age_hours, 2)
    metrics["input_modified_at_utc"] = decision.source_modified_at.isoformat()
    print(decision, flush=True)

    if not decision.fresh and not options.skip_freshness_gate:
        metrics["refusal_reason"] = "stale_input"
        write_metrics(metrics)
        print("\nSTALE INPUT — published nothing.")
        print("A missing call list is noticed in minutes. A plausible wrong one is "
              "worked through for a day.")
        return 2

    if not decision.fresh:
        print("\n*** freshness gate skipped: scoring a stale input on purpose ***\n")
        metrics["gate_skipped"] = True

    # --- the data contract -------------------------------------------------------------
    frame = pd.read_csv(options.input, sep=";")
    metrics["rows_in"] = len(frame)

    violations = contract.validate(frame)
    if violations:
        metrics["refusal_reason"] = "contract_violation"
        metrics["violations"] = [str(violation) for violation in violations]
        write_metrics(metrics)
        print("\nCONTRACT VIOLATION — published nothing:")
        for violation in violations:
            print(f"  {violation}")
        return 3

    # --- score and rank ----------------------------------------------------------------
    if not options.model.exists():
        metrics["refusal_reason"] = "model_missing"
        write_metrics(metrics)
        print(f"\nno model at {options.model}; published nothing")
        return 4

    model = joblib.load(options.model)
    scored = frame.copy()
    scored["score"] = model.predict_proba(features.build_features(frame))[:, 1]
    call_list = scored.sort_values("score", ascending=False).head(options.call_budget)

    options.out_dir.mkdir(parents=True, exist_ok=True)
    output_path = options.out_dir / f"call-list-{now:%Y-%m-%d}.csv"
    call_list.to_csv(output_path, index=False)

    metrics.update({
        "published": True,
        "rows_published": len(call_list),
        "score_median": round(float(call_list["score"].median()), 4),
        "score_min": round(float(call_list["score"].min()), 4),
        "score_max": round(float(call_list["score"].max()), 4),
        "duration_seconds": round(
            (datetime.now(timezone.utc) - started_at).total_seconds(), 2),
        "output": str(output_path),
    })
    write_metrics(metrics)

    print(f"\npublished {len(call_list)} customers to {output_path}")
    print(f"score range {metrics['score_min']} to {metrics['score_max']}, "
          f"median {metrics['score_median']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
