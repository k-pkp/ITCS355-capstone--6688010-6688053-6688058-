"""The nightly job: read tomorrow's contact list, rank it, publish it.

    python scripts/score_nightly.py --input data/bank/incoming/contacts.csv

This is what Cloud Scheduler runs. Six steps, about a minute:

    read input -> FRESHNESS GATE -> data contract -> APPROVED MODEL -> score -> publish

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

from src.bank import cloud, contract, features, freshness, promotion

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
OUTPUT_DIR = PROJECT_ROOT / "data" / "bank" / "call-lists"
METRICS_PATH = REPORTS_DIR / "nightly-metrics.json"
DEFAULT_MODEL = REPORTS_DIR / "bank-model.joblib"
APPROVAL_PATH = REPORTS_DIR / "approved-model.json"


def parse_command_line() -> argparse.Namespace:
    """Command line for the nightly scoring job."""
    parser = argparse.ArgumentParser(description="Score and rank tomorrow's contact list")
    parser.add_argument("--input", type=Path, default=None,
                        help="a local customer export to score")
    parser.add_argument("--input-object", default=None,
                        help="an object in the project bucket to score instead of a local "
                             "file, e.g. capstone/incoming/contacts.csv. This is what the "
                             "scheduled run uses.")
    parser.add_argument("--publish-prefix", default=None,
                        help="bucket prefix to publish the call list under; implies the "
                             "run is a cloud run")
    parser.add_argument("--emit-metrics", action="store_true",
                        help="send this run's numbers to Cloud Monitoring")
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

    if options.input is None and options.input_object is None:
        raise SystemExit("pass --input for a local file or --input-object for the bucket")

    # A bucket object is fetched first, and its age is taken from the object's own
    # metadata rather than from the downloaded copy, whose modification time would be
    # the moment we downloaded it -- which is always now, and always fresh.
    remote_age_hours = None
    if options.input_object is not None:
        local_copy = Path("/tmp/nightly-input.csv")
        try:
            described = cloud.download(options.input_object, local_copy)
        except FileNotFoundError:
            metrics["refusal_reason"] = "input_missing"
            write_metrics(metrics)
            if options.emit_metrics:
                cloud.emit_metrics({"published": 0, "refused": 1})
            print(f"gs://{cloud.BUCKET}/{options.input_object} does not exist; "
                  f"published nothing")
            return 1

        options.input = local_copy
        remote_age_hours = (now - described.updated_at).total_seconds() / 3600
        metrics["input"] = described.uri
        print(f"fetched {described.uri} ({described.size_bytes:,} bytes)", flush=True)

    if not options.input.exists():
        metrics["refusal_reason"] = "input_missing"
        write_metrics(metrics)
        print(f"input {options.input} does not exist; published nothing")
        return 1

    # --- the freshness gate ------------------------------------------------------------
    if remote_age_hours is not None:
        from datetime import timedelta
        decision = freshness.FreshnessDecision(
            fresh=remote_age_hours <= freshness.MAXIMUM_INPUT_AGE.total_seconds() / 3600,
            age=timedelta(hours=remote_age_hours),
            source_modified_at=now - timedelta(hours=remote_age_hours),
            checked_at=now,
        )
    else:
        decision = freshness.check(options.input, now=now)
    metrics["input_age_hours"] = round(decision.age_hours, 2)
    metrics["input_modified_at_utc"] = decision.source_modified_at.isoformat()
    print(decision, flush=True)

    if not decision.fresh and not options.skip_freshness_gate:
        metrics["refusal_reason"] = "stale_input"
        write_metrics(metrics)
        if options.emit_metrics:
            cloud.emit_metrics({"published": 0, "refused": 1,
                                "input_age_hours": metrics["input_age_hours"]})
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
        if options.emit_metrics:
            cloud.emit_metrics({"published": 0, "refused": 1,
                                "contract_violations": len(violations)})
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

    # The model is checked against the approval record before it is loaded. Without this
    # the job scores whatever file is at that path, and "which model is in production" is
    # answered by a build log rather than by the running system.
    try:
        verified_hash = promotion.require_approved_model(options.model, APPROVAL_PATH)
    except promotion.UnapprovedModelError as refusal:
        metrics["refusal_reason"] = "unapproved_model"
        metrics["detail"] = str(refusal)
        write_metrics(metrics)
        if options.emit_metrics:
            cloud.emit_metrics({"published": 0, "refused": 1})
        print(f"\nUNAPPROVED MODEL — published nothing:\n  {refusal}")
        return 5

    print(f"model {verified_hash[:16]}… matches the approved one", flush=True)
    metrics["model_sha256"] = verified_hash

    model = joblib.load(options.model)
    scored = frame.copy()
    scored["score"] = model.predict_proba(features.build_features(frame))[:, 1]
    call_list = scored.sort_values("score", ascending=False).head(options.call_budget)

    options.out_dir.mkdir(parents=True, exist_ok=True)
    output_path = options.out_dir / f"call-list-{now:%Y-%m-%d}.csv"
    call_list.to_csv(output_path, index=False)

    if options.publish_prefix is not None:
        published_uri = cloud.upload(
            output_path, f"{options.publish_prefix}/call-list-{now:%Y-%m-%d}.csv")
        metrics["published_uri"] = published_uri
        print(f"published to {published_uri}", flush=True)

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

    if options.emit_metrics:
        written = cloud.emit_metrics({
            "published": 1,
            "refused": 0,
            "rows_in": metrics["rows_in"],
            "rows_published": metrics["rows_published"],
            "input_age_hours": metrics.get("input_age_hours", 0),
            "duration_seconds": metrics["duration_seconds"],
        })
        print(f"emitted {len(written)} metrics to Cloud Monitoring")

    print(f"\npublished {len(call_list)} customers to {output_path}")
    print(f"score range {metrics['score_min']} to {metrics['score_max']}, "
          f"median {metrics['score_median']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
