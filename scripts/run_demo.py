"""Run the capstone demonstration end to end, one refusal at a time.

    python scripts/run_demo.py              # the whole sequence
    python scripts/run_demo.py --only stale # one scene, for rehearsing

Written as a script rather than a list of commands in a runbook because a demo typed live
is a demo that can fail on a typo in front of the person grading it. Every scene here runs
the real `score_nightly.py` against a real file and reports the real exit code. Nothing is
printed that the job did not actually produce.

The order is deliberate. The happy path comes first so the audience knows what success looks
like; every scene after it is the same system refusing to do something, for a different
reason, with a different exit code. That is the argument the project is making: a batch job
that cannot refuse will eventually publish something wrong and look fine doing it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bank import splits

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"
SERVING_MODEL = PROJECT_ROOT / "reports" / "bank-model.joblib"
DEMO_DIR = Path("/tmp/itcs355-demo")

# The exit code each scene should produce. Stated here rather than read from the run, so a
# scene that starts returning something else fails the demo instead of narrating it.
EXPECTED_EXIT_CODES = {
    "happy": 0,
    "stale": 2,
    "category": 3,
    "empty": 3,
    "model": 5,
}


def announce(scene: str, title: str, why: str) -> None:
    """Print the heading for one scene."""
    print(f"\n{'=' * 78}")
    print(f"  {scene.upper()}  —  {title}")
    print(f"  {why}")
    print("=" * 78, flush=True)


def run_nightly_job(input_path: Path, extra_arguments: list[str] | None = None) -> int:
    """Run the real scoring job against one file and return its exit code."""
    command = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "score_nightly.py"),
        "--input", str(input_path),
        "--call-share", "0.1667",
        "--out-dir", str(DEMO_DIR / "call-lists"),
    ]
    command += extra_arguments or []

    result = subprocess.run(command, cwd=PROJECT_ROOT)
    return result.returncode


def build_todays_export() -> Path:
    """Write one night of the replayed campaign as a fresh local export."""
    dataset = pd.read_csv(DATASET, sep=";")
    held_out = splits.split_by_time(dataset).test
    tonight = held_out.iloc[:600]

    export_path = DEMO_DIR / "contacts.csv"
    tonight.to_csv(export_path, sep=";", index=False)
    return export_path


def scene_happy(export_path: Path) -> int:
    """The normal night: a fresh export, every gate satisfied, a list published."""
    announce("happy", "A normal night",
             "Fresh export, every check passes, the call list is published.")
    return run_nightly_job(export_path)


def scene_stale(export_path: Path) -> int:
    """The engineered failure: yesterday's file, still perfectly valid."""
    announce("stale", "The failure we engineered — yesterday's export",
             "The overnight export never arrived. Yesterday's file is still there, and "
             "every structural check it faces will pass.")

    stale_path = DEMO_DIR / "contacts-stale.csv"
    shutil.copy(export_path, stale_path)

    two_days_ago = datetime.now() - timedelta(days=2)
    timestamp = two_days_ago.timestamp()
    import os
    os.utime(stale_path, (timestamp, timestamp))

    return run_nightly_job(stale_path)


def scene_category(export_path: Path) -> int:
    """Unexpected input: a job category the contract has never seen."""
    announce("category", "Unexpected input — a job category we have never seen",
             "This is the one the instructor is most likely to send. The file is valid "
             "CSV, the right shape, and contains a value the model was never trained on.")

    frame = pd.read_csv(export_path, sep=";")
    frame.loc[frame.index[:40], "job"] = "influencer"

    surprising_path = DEMO_DIR / "contacts-unknown-category.csv"
    frame.to_csv(surprising_path, sep=";", index=False)
    return run_nightly_job(surprising_path)


def scene_empty(export_path: Path) -> int:
    """Unexpected input: the export ran, produced headers, and no rows."""
    announce("empty", "Unexpected input — an export with no rows",
             "The upstream job succeeded and wrote nothing. Before this was a contract "
             "rule it reached the model and raised a library error about array shapes.")

    frame = pd.read_csv(export_path, sep=";")
    empty_path = DEMO_DIR / "contacts-empty.csv"
    frame.iloc[0:0].to_csv(empty_path, sep=";", index=False)
    return run_nightly_job(empty_path)


def scene_model(export_path: Path) -> int:
    """A model nobody approved, sitting where the approved one should be."""
    announce("model", "A model the gate never saw",
             "Nothing is wrong with this model. It loads, it scores, it would publish a "
             "list. It is simply not the one the gate approved.")

    from sklearn.ensemble import HistGradientBoostingClassifier

    from src.bank import features

    dataset = pd.read_csv(DATASET, sep=";")
    other_window = splits.split_by_time(dataset).train.iloc[-2000:]
    other_model = HistGradientBoostingClassifier(random_state=999)
    other_model.fit(features.build_features(other_window),
                    features.build_target(other_window))

    substitute_path = DEMO_DIR / "unapproved-model.joblib"
    joblib.dump(other_model, substitute_path)

    return run_nightly_job(export_path, ["--model", str(substitute_path)])


SCENES = {
    "happy": scene_happy,
    "stale": scene_stale,
    "category": scene_category,
    "empty": scene_empty,
    "model": scene_model,
}


def parse_command_line() -> argparse.Namespace:
    """Command line for the demonstration."""
    parser = argparse.ArgumentParser(description="Run the capstone demonstration")
    parser.add_argument("--only", choices=sorted(SCENES),
                        help="run one scene, for rehearsing a single moment")
    return parser.parse_args()


def main() -> int:
    """Run every scene and report whether each refused for the reason it should."""
    options = parse_command_line()
    if not DATASET.exists():
        raise SystemExit(f"{DATASET} not found; run `dvc pull`")

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    (DEMO_DIR / "call-lists").mkdir(exist_ok=True)
    export_path = build_todays_export()

    scenes_to_run = [options.only] if options.only else list(SCENES)
    outcomes = []

    for scene_name in scenes_to_run:
        exit_code = SCENES[scene_name](export_path)
        expected = EXPECTED_EXIT_CODES[scene_name]
        outcomes.append((scene_name, exit_code, expected))
        print(f"\n  exit code {exit_code} (expected {expected})", flush=True)

    print(f"\n{'=' * 78}")
    print("  SUMMARY")
    print("=" * 78)
    for scene_name, exit_code, expected in outcomes:
        verdict = "as designed" if exit_code == expected else "UNEXPECTED"
        print(f"  {scene_name:<10} exit {exit_code}  (expected {expected})  {verdict}")

    everything_as_designed = all(actual == expected
                                 for _, actual, expected in outcomes)
    if not everything_as_designed:
        print("\n  A scene did not behave as designed. Do not present this until it does.")
        return 1

    print("\n  Every scene behaved as designed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
