"""Run the capstone demonstration end to end, one refusal at a time.

    python scripts/run_demo.py              # the five scenes of the talk
    python scripts/run_demo.py --all        # those five, then three more
    python scripts/run_demo.py --only drift # one scene, for rehearsing

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
    "nogate": 0,
    "drift": 2,
    "guard": 0,
}

# The five that tell the story in two minutes. The rest are held back so the
# demonstration stays the length it was rehearsed at.
CORE_SCENES = ("happy", "stale", "category", "empty", "model")

# Run with --all. Each one answers a question that has been asked before, and none
# of them needs the cloud.
EXTRA_SCENES = ("nogate", "drift", "guard")


def use_utf8_for_output() -> None:
    """Print UTF-8 whatever the console's own encoding is.

    The scenes print em dashes and times signs. Windows gives a redirected stream the
    system code page rather than UTF-8, so `python scripts/run_demo.py > out.txt`
    raised UnicodeEncodeError on a teammate's machine while the same command printed
    fine to his terminal. Reconfiguring here costs nothing and removes the difference.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            # Already wrapped, or not a real stream. Nothing to do.
            pass


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


def scene_nogate(export_path: Path) -> int:
    """The same stale file again, with the freshness gate switched off.

    Scene two shows the job refusing. This shows what it was refusing to do, which is
    the part an examiner cannot otherwise see: the run succeeds, a full call list goes
    out, and nothing anywhere reports a problem.
    """
    announce("nogate", "The counterfactual — the same stale file, gate off",
             "Yesterday's export again, scored with --skip-freshness-gate. This is what "
             "the gate was preventing.")

    stale_path = DEMO_DIR / "contacts-stale.csv"
    if not stale_path.exists():
        shutil.copy(export_path, stale_path)
    two_days_ago = datetime.now() - timedelta(days=2)
    timestamp = two_days_ago.timestamp()
    import os
    os.utime(stale_path, (timestamp, timestamp))

    return run_nightly_job(stale_path, ["--skip-freshness-gate"])


def scene_drift(export_path: Path) -> int:
    """The drift detector, scoring the held-out period against the training window.

    Nothing in the nightly job notices that the world has moved; this is the check that
    does. It writes its report into the demo directory rather than into reports/, so a
    rehearsal does not leave the repository dirty.
    """
    announce("drift", "Drift — has the world moved since training?",
             "PSI for every column the model reads, current period against the window "
             "it was trained on.")

    command = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "check_drift.py"),
        "--out", str(DEMO_DIR / "bank-drift.md"),
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    return result.returncode


def scene_guard(export_path: Path) -> int:
    """The two tests CI runs on every push to keep the leakage traps shut.

    They pass, which is the point: these are the checks standing between the repository
    and the two mistakes that made the model look good and were not.
    """
    announce("guard", "The guards CI runs on every push",
             "One asserts the call duration never reaches the model. One asserts the "
             "split is never shuffled.")

    command = [
        sys.executable, "-m", "pytest", "-q",
        "tests/bank/test_features.py::test_duration_never_reaches_the_model",
        "tests/bank/test_splits.py",
        "-k", "duration or shuffle or chronological",
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    return result.returncode


SCENES = {
    "happy": scene_happy,
    "stale": scene_stale,
    "category": scene_category,
    "empty": scene_empty,
    "model": scene_model,
    "nogate": scene_nogate,
    "drift": scene_drift,
    "guard": scene_guard,
}


def parse_command_line() -> argparse.Namespace:
    """Command line for the demonstration."""
    parser = argparse.ArgumentParser(description="Run the capstone demonstration")
    parser.add_argument("--only", choices=sorted(SCENES),
                        help="run one scene, for rehearsing a single moment")
    parser.add_argument("--all", action="store_true",
                        help="run the three extra scenes after the five of the talk")
    parser.add_argument("--pause", action="store_true",
                        help="wait for Enter between scenes, for presenting live")
    return parser.parse_args()


def wait_for_presenter(next_scene: str) -> None:
    """Hold between scenes so the room can read one refusal before the next.

    The whole sequence runs in about five seconds, which is faster than anybody can
    explain it. Presented live, the pause is what turns five exit codes into five
    separate points.
    """
    try:
        input(f"\n  [Enter] for the next scene: {next_scene}  ")
    except EOFError:
        # Nothing on standard input, which is the case in CI. Carry on without pausing.
        pass


def main() -> int:
    """Run every scene and report whether each refused for the reason it should."""
    use_utf8_for_output()
    options = parse_command_line()
    if not DATASET.exists():
        raise SystemExit(f"{DATASET} not found; run `dvc pull`")

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    (DEMO_DIR / "call-lists").mkdir(exist_ok=True)
    export_path = build_todays_export()

    if options.only:
        scenes_to_run = [options.only]
    elif options.all:
        scenes_to_run = list(CORE_SCENES) + list(EXTRA_SCENES)
    else:
        scenes_to_run = list(CORE_SCENES)
    outcomes = []

    for scene_index, scene_name in enumerate(scenes_to_run):
        if options.pause and scene_index > 0:
            wait_for_presenter(scene_name)
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
