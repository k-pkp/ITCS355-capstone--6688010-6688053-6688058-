"""Register the trained model, if the evaluation gate lets it through.

    python scripts/register_bank_model.py

Trains the candidate, measures it against the baselines, assembles the lineage, and asks
the gate. On a pass the model is registered in MLflow with every lineage field attached. On
a refusal nothing is registered and the script exits non-zero.

The refusal path is the one that matters. A gate only ever exercised by models that pass is
a gate nobody has seen work, and the first time it blocks something will be the first time
anyone finds out whether it can.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.train_bank import SEED, TRAINING_WINDOW_ROWS, recent_window, train_model
from src.bank import contract, evaluate, features, gate, splits

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"
DATASET_POINTER = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv.dvc"
REPORTS_DIR = PROJECT_ROOT / "reports"

MODEL_NAME = "bank-call-list-ranker"
MLFLOW_TRACKING_URI = f"sqlite:///{PROJECT_ROOT / 'mlflow.db'}"


def parse_command_line() -> argparse.Namespace:
    """Command line for registration."""
    parser = argparse.ArgumentParser(description="Register the model, if the gate allows")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--call-budget", type=int, default=evaluate.DEFAULT_CALL_BUDGET)
    parser.add_argument("--model-name", default=MODEL_NAME)
    parser.add_argument("--train-window", type=int, default=TRAINING_WINDOW_ROWS,
                        help="how many of the most recent rows before the split point to "
                             "train on; 0 means all of them")
    return parser.parse_args()


def current_git_commit() -> str:
    """Return the full commit hash, or an empty string if it cannot be determined.

    An empty string is returned rather than the word "unknown" on purpose. The gate treats
    both as missing, and returning a plausible-looking placeholder is how a lineage field
    ends up populated with nothing.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    return result.stdout.strip() if result.returncode == 0 else ""


def dataset_fingerprint(path: Path) -> str:
    """Return the SHA-256 of the dataset file itself."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dvc_data_version(pointer_path: Path) -> str:
    """Return the DVC content hash recorded for the dataset.

    This is what makes the dataset recoverable: the file's own SHA answers "is this the
    same bytes", and the DVC hash answers "which versioned copy do I pull to get them".
    """
    if not pointer_path.exists():
        return ""

    for line in pointer_path.read_text().splitlines():
        # The hash sits under a YAML list item, so the line reads "- md5: ..." rather
        # than "md5: ...". Matching only the latter returned an empty string, and the
        # gate refused the registration for a missing lineage field -- which is how this
        # bug was found rather than shipped.
        stripped = line.strip().lstrip("-").strip()
        if stripped.startswith("md5:"):
            return stripped.split("md5:", 1)[1].strip()
    return ""


def feature_names_fingerprint() -> str:
    """Return a hash of the feature column names, in order.

    Two models with different feature orders are different models, and a name list that
    quietly changed between training and serving is the cause of a class of bug that looks
    like the model went mad.
    """
    joined = "\n".join(features.feature_names())
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def register_in_mlflow(model, lineage: dict, model_name: str) -> str:
    """Record the model and its lineage, returning the registered version."""
    import mlflow
    import mlflow.sklearn

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("bank-call-list")

    with mlflow.start_run(run_name=f"gate-pass-{lineage['git_commit'][:8]}"):
        mlflow.log_params({
            "seed": lineage["seed"],
            "train_rows": lineage["train_rows"],
            "call_budget": lineage["call_budget"],
        })
        mlflow.log_metric("lift", lineage["metric_lift"])
        mlflow.set_tags({key: str(value) for key, value in lineage.items()})

        # MLflow refuses to serialise this model type without being told it is trusted.
        # The warning is about loading a model file from somewhere else: the tree predictor
        # stores raw node indices that scikit-learn indexes without bounds checking, so a
        # crafted file can crash the process. This model was fitted a few lines ago in this
        # same process, and the one type named here is the only one being trusted.
        info = mlflow.sklearn.log_model(
            model, name="model",
            skops_trusted_types=[
                "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"
            ],
        )
        version = mlflow.register_model(model_uri=info.model_uri, name=model_name)

        client = mlflow.MlflowClient()
        for key, value in lineage.items():
            client.set_model_version_tag(model_name, version.version, key, str(value))

    return version.version


def main() -> int:
    """Train a candidate, ask the gate, and register only on a pass."""
    options = parse_command_line()
    if not options.dataset.exists():
        raise SystemExit(f"{options.dataset} not found; run `dvc pull`")

    dataset = pd.read_csv(options.dataset, sep=";")
    violations = contract.validate(dataset)
    if violations:
        raise SystemExit("the dataset fails its contract:\n" +
                         "\n".join(str(violation) for violation in violations))

    split = splits.split_by_time(dataset)
    history = pd.concat([split.train, split.validation])
    training_frame = recent_window(history, options.train_window)

    train_features = features.build_features(training_frame)
    train_target = features.build_target(training_frame)
    test_features = features.build_features(split.test)
    test_target = features.build_target(split.test).to_numpy()

    print(f"training on {len(training_frame):,} rows", flush=True)
    model = train_model(train_features, train_target)

    # Scored the way the deployed job is judged: inside one month's calls, never across
    # the whole period. reports/bank-export-evaluation.md has why that distinction decides
    # whether this model passes or fails.
    candidate = evaluate.score_within_contact_months(
        model.predict_proba(test_features)[:, 1], test_target, split.test)

    baselines = {
        "file_order": evaluate.score_within_contact_months(
            evaluate.baseline_file_order(split.test), test_target, split.test),
        "euribor3m": evaluate.score_within_contact_months(
            evaluate.baseline_single_column(split.test), test_target, split.test),
    }

    lineage = {
        "git_commit": current_git_commit(),
        "data_sha256": dataset_fingerprint(options.dataset),
        "data_version": dvc_data_version(DATASET_POINTER),
        "seed": SEED,
        "feature_names_hash": feature_names_fingerprint(),
        "train_rows": len(training_frame),
        "metric_lift": round(candidate.lift, 4),
        "metric": "within-month lift at the supervisor's call share",
        "worst_month_lift": round(candidate.worst_month_lift, 4),
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "call_budget": options.call_budget,
    }

    print(f"\ncandidate  {candidate}")
    for name, score in baselines.items():
        print(f"baseline   {name}: lift {score.lift:.2f}x")

    decision = gate.evaluate_candidate(candidate, baselines, lineage)
    print(f"\n{decision}\n")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "bank-gate-decision.json").write_text(json.dumps({
        "decided_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": decision.passed,
        "reasons": decision.reasons,
        "candidate_lift": candidate.lift,
        "candidate_worst_month_lift": candidate.worst_month_lift,
        # A list rather than a dict keyed by month name. The campaign spans two and a half
        # years, so "may" appears three times in the test period, and a dict silently kept
        # the last one -- thirteen measured months written out as eight.
        "candidate_month_lifts": [
            {"month": label, "rows": rows, "lift": lift}
            for label, rows, lift in zip(candidate.month_labels,
                                         candidate.month_rows,
                                         candidate.month_lifts)
        ],
        "baseline_lifts": {name: score.lift for name, score in baselines.items()},
        "minimum_margin": gate.MINIMUM_LIFT_MARGIN,
        "lineage": lineage,
    }, indent=2))

    if not decision.passed:
        print("nothing was registered.")
        print("The gate is doing its job. The decision and its reasons are in "
              "reports/bank-gate-decision.json, which is the record of what was refused "
              "and why -- a registry holding only models that passed cannot answer that.")
        return 1

    joblib.dump(model, REPORTS_DIR / "bank-model.joblib")
    version = register_in_mlflow(model, lineage, options.model_name)
    print(f"registered {options.model_name} version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
