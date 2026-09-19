"""Train the call-list ranker, and report it against the baselines it must beat.

    python scripts/train_bank.py

Writes reports/bank-training.md and reports/bank-model.joblib.

The script also runs one experiment that is not about choosing a model: it trains a second
model *with* the `duration` column, to measure what the leakage trap is worth. That number
is the argument for a test that most reviewers would otherwise read as excessive caution.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bank import contract, evaluate, features, splits

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

SEED = 20260101


def parse_command_line() -> argparse.Namespace:
    """Command line for training."""
    parser = argparse.ArgumentParser(description="Train the call-list ranker")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--call-budget", type=int, default=evaluate.DEFAULT_CALL_BUDGET)
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    return parser.parse_args()


def train_model(train_features: pd.DataFrame, train_target: pd.Series,
                seed: int = SEED) -> HistGradientBoostingClassifier:
    """Fit the ranker.

    A histogram gradient-boosted tree, with defaults. The brief awards no marks for model
    accuracy, so the model is the cheapest thing that beats the baselines, and tuning it
    would spend time the failure demonstration needs.
    """
    model = HistGradientBoostingClassifier(random_state=seed)
    model.fit(train_features, train_target)
    return model


def score_with_duration(dataset: pd.DataFrame, split: splits.Split,
                        call_budget: int) -> evaluate.RankingScore:
    """Measure what including the leakage column would appear to buy.

    This model is never deployed and never registered. It exists to put a number on the
    trap, because "duration is leakage" is an assertion and "including it appears to add
    2.4x lift, all of it unavailable at prediction time" is an argument.
    """
    def build_with_duration(frame: pd.DataFrame) -> pd.DataFrame:
        """Build the normal features, then add back the column we exclude on purpose."""
        base = features.build_features(frame)
        base = base.copy()
        base["duration"] = frame["duration"].to_numpy()
        return base

    train_features = build_with_duration(split.train)
    train_target = features.build_target(split.train)
    test_features = build_with_duration(split.test)
    test_target = features.build_target(split.test)

    leaky_model = train_model(train_features, train_target)
    scores = leaky_model.predict_proba(test_features)[:, 1]
    return evaluate.score_ranking(scores, test_target.to_numpy(), call_budget)


def main() -> int:
    """Train, evaluate against the baselines, and write the report."""
    options = parse_command_line()
    if not options.dataset.exists():
        raise SystemExit(
            f"{options.dataset} not found. Run scripts/download_bank_data.py or `dvc pull`."
        )

    dataset = pd.read_csv(options.dataset, sep=";")

    violations = contract.validate(dataset)
    if violations:
        raise SystemExit("the dataset fails its contract:\n" +
                         "\n".join(str(violation) for violation in violations))

    split = splits.split_by_time(dataset)
    print(split.describe())
    print(splits.describe_shift(split), "\n", flush=True)

    train_features = features.build_features(split.train)
    train_target = features.build_target(split.train)
    test_features = features.build_features(split.test)
    test_target = features.build_target(split.test).to_numpy()

    model = train_model(train_features, train_target)
    model_scores = model.predict_proba(test_features)[:, 1]

    results = {
        "model": evaluate.score_ranking(model_scores, test_target, options.call_budget),
        "baseline_file_order": evaluate.score_ranking(
            evaluate.baseline_file_order(split.test), test_target, options.call_budget),
        "baseline_euribor": evaluate.score_ranking(
            evaluate.baseline_single_column(split.test), test_target, options.call_budget),
    }

    print("on the held-out test period:")
    for name, score in results.items():
        print(f"  {name:<22} {score}")

    leaky = score_with_duration(dataset, split, options.call_budget)
    print(f"\n  {'with duration (leaky)':<22} {leaky}")

    options.out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, options.out_dir / "bank-model.joblib")

    lines = [
        "# Training report — call-list ranker",
        "",
        f"Seed {SEED}. Split in stored campaign order: {split.describe()}.",
        "",
        splits.describe_shift(split),
        "",
        "## Ranked against the baselines",
        "",
        f"Measured on the held-out final period, at a call budget of "
        f"{options.call_budget}.",
        "",
        "| Ranking | Subscriptions in top | Hit rate | Lift over random |",
        "|---|--:|--:|--:|",
    ]
    for name, score in results.items():
        lines.append(f"| {name.replace('_', ' ')} | {score.hits} | "
                     f"{score.hit_rate:.1%} | {score.lift:.2f}x |")

    lines += [
        "",
        "The test period's base rate is "
        f"{test_target.mean():.1%}, so calling {options.call_budget} people at random "
        f"yields about {test_target.mean() * options.call_budget:.0f} subscriptions.",
        "",
        "Accuracy is deliberately not reported as a headline. At this base rate a model "
        "that predicts 'no' for everybody is "
        f"{1 - dataset['y'].eq('yes').mean():.1%} accurate and produces no call list.",
        "",
        "## What the leakage column would appear to buy",
        "",
        f"A second model trained with `duration` included scores **{leaky.lift:.2f}x** "
        f"lift against the deployed model's **{results['model'].lift:.2f}x**.",
        "",
        "That difference is not available at prediction time. `duration` is how long the "
        "call lasted, and the call has not happened when the list is built. The second "
        "model is never registered and never deployed; it exists to put a number on the "
        "trap, because 'duration is leakage' is an assertion and this is an argument.",
        "",
        "`tests/bank/test_features.py::test_duration_never_reaches_the_model` is what "
        "keeps it out.",
        "",
    ]
    (options.out_dir / "bank-training.md").write_text("\n".join(lines))

    metrics = {
        "seed": SEED,
        "call_budget": options.call_budget,
        "train_rows": len(split.train),
        "test_rows": len(split.test),
        "train_subscribe_rate": splits.subscribe_rate(split.train),
        "test_subscribe_rate": splits.subscribe_rate(split.test),
        "model_lift": results["model"].lift,
        "baseline_file_order_lift": results["baseline_file_order"].lift,
        "baseline_euribor_lift": results["baseline_euribor"].lift,
        "leaky_duration_lift": leaky.lift,
    }
    (options.out_dir / "bank-metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"\nwrote {options.out_dir / 'bank-training.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
