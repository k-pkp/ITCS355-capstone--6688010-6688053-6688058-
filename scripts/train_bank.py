"""Train the call-list ranker, and report it against the baselines it must beat.

    python scripts/train_bank.py

Writes reports/bank-training.md and reports/bank-model.joblib.

The script also runs one experiment that is not about choosing a model: it trains a second
model *with* the `duration` column, to measure what the leakage trap is worth. That number
is the argument for a test that most reviewers would otherwise read as excessive caution.

Two decisions here were measured rather than assumed, and both are recorded in
reports/bank-export-evaluation.md:

**The model trains on a recent window, not on all history.** The campaign spans a financial
crisis. Training on everything means fitting mostly to 2008-2009, when almost nobody
subscribed, and then ranking customers in a 2010 world where many did. The window size was
chosen on the validation period and never on the test period.

**The headline number is lift within one contact month.** Lift across the whole test period
rewards a ranking for sorting the calendar, which the deployed job is never asked to do.
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

# The model trains on the most recent rows before the split point rather than on everything.
# Chosen by sweeping 4,000 / 8,000 / 12,000 / 16,000 / 20,000 / all on the validation
# period, at the within-month measurement: 4,000 scored 1.071x and every larger window
# scored below 1.0. The test period was not involved in this choice.
TRAINING_WINDOW_ROWS = 4000


def parse_command_line() -> argparse.Namespace:
    """Command line for training."""
    parser = argparse.ArgumentParser(description="Train the call-list ranker")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--call-budget", type=int, default=evaluate.DEFAULT_CALL_BUDGET)
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--train-window", type=int, default=TRAINING_WINDOW_ROWS,
                        help="how many of the most recent rows before the split point to "
                             "train on; 0 means all of them")
    return parser.parse_args()


def recent_window(history: pd.DataFrame, window_rows: int) -> pd.DataFrame:
    """Return the most recent rows of the training history, or all of them if asked."""
    if window_rows <= 0 or window_rows >= len(history):
        return history
    return history.iloc[-window_rows:]


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


def score_with_duration(training_frame: pd.DataFrame,
                        test_frame: pd.DataFrame) -> evaluate.WithinMonthScore:
    """Measure what including the leakage column would appear to buy.

    Trained on the same rows as the real model, so the only difference between the two
    numbers is the forbidden column. This model is never deployed and never registered. It
    exists to put a number on the trap, because "duration is leakage" is an assertion and
    "including it appears to add this much lift, all of it unavailable at prediction time"
    is an argument.
    """
    def build_with_duration(frame: pd.DataFrame) -> pd.DataFrame:
        """Build the normal features, then add back the column we exclude on purpose."""
        base = features.build_features(frame).copy()
        base["duration"] = frame["duration"].to_numpy()
        return base

    leaky_model = train_model(build_with_duration(training_frame),
                              features.build_target(training_frame))
    scores = leaky_model.predict_proba(build_with_duration(test_frame))[:, 1]
    test_target = features.build_target(test_frame).to_numpy()
    return evaluate.score_within_contact_months(scores, test_target, test_frame)


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

    # Everything before the test period is available for training. The validation period is
    # not held back from the shipped model -- it was used to choose the window size, and
    # once that choice is made, throwing away the most recent eight thousand rows would
    # ship a model deliberately blinder than it needs to be.
    history = pd.concat([split.train, split.validation])
    training_frame = recent_window(history, options.train_window)
    print(f"training on the most recent {len(training_frame):,} of {len(history):,} rows "
          f"before the test period")

    train_features = features.build_features(training_frame)
    train_target = features.build_target(training_frame)
    test_features = features.build_features(split.test)
    test_target = features.build_target(split.test).to_numpy()

    model = train_model(train_features, train_target)
    model_scores = model.predict_proba(test_features)[:, 1]
    file_order_scores = evaluate.baseline_file_order(split.test)
    euribor_scores = evaluate.baseline_single_column(split.test)

    # The measurement the deployed job is judged by: ranking inside one month's calls.
    within_month = {
        "model": evaluate.score_within_contact_months(
            model_scores, test_target, split.test),
        "baseline_file_order": evaluate.score_within_contact_months(
            file_order_scores, test_target, split.test),
        "baseline_euribor": evaluate.score_within_contact_months(
            euribor_scores, test_target, split.test),
    }

    # The measurement the first version of this project reported, kept because the gap
    # between the two is the project's main finding rather than an embarrassment.
    whole_period = {
        "model": evaluate.score_ranking(model_scores, test_target, options.call_budget),
        "baseline_file_order": evaluate.score_ranking(
            file_order_scores, test_target, options.call_budget),
        "baseline_euribor": evaluate.score_ranking(
            euribor_scores, test_target, options.call_budget),
    }

    print("\nranked inside one contact month, which is what the job does:")
    for name, score in within_month.items():
        print(f"  {name:<22} {score}")

    print("\nranked across the whole test period at once, which it never does:")
    for name, score in whole_period.items():
        print(f"  {name:<22} lift {score.lift:.2f}x")

    leaky = score_with_duration(training_frame, split.test)
    print(f"\n  {'with duration (leaky)':<22} {leaky}")

    options.out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, options.out_dir / "bank-model.joblib")

    lines = [
        "# Training report — call-list ranker",
        "",
        f"Seed {SEED}. Split in stored campaign order: {split.describe()}.",
        f"Trained on the most recent {len(training_frame):,} rows before the test period.",
        "",
        splits.describe_shift(split),
        "",
        "## Ranked inside one contact month",
        "",
        "This is the measurement the deployed job is judged by. It ranks the calls made "
        "within a single month against each other, because that is the only comparison "
        "the job is ever asked to make — it receives one export and decides who in that "
        "export to call first.",
        "",
        "| Ranking | Lift, weighted across months | Worst month | Months measured |",
        "|---|--:|--:|--:|",
    ]
    for name, score in within_month.items():
        lines.append(f"| {name.replace('_', ' ')} | {score.lift:.2f}x | "
                     f"{score.worst_month_lift:.2f}x | {len(score.month_lifts)} |")

    lines += [
        "",
        "### Month by month",
        "",
        "| Month block | Rows | Model | euribor3m |",
        "|---|--:|--:|--:|",
    ]
    for position, label in enumerate(within_month["model"].month_labels):
        lines.append(
            f"| {label} | {within_month['model'].month_rows[position]:,} | "
            f"{within_month['model'].month_lifts[position]:.2f}x | "
            f"{within_month['baseline_euribor'].month_lifts[position]:.2f}x |"
        )

    lines += [
        "",
        "## Ranked across the whole test period at once",
        "",
        "Kept because the gap between this table and the one above is the main finding of "
        "the project, not an embarrassment to be tidied away. Ranking the whole period "
        "rewards a ranking for sorting the calendar — information the job does not have, "
        "because every customer in one export was contacted at roughly the same time.",
        "",
        "| Ranking | Subscriptions in top | Hit rate | Lift over random |",
        "|---|--:|--:|--:|",
    ]
    for name, score in whole_period.items():
        lines.append(f"| {name.replace('_', ' ')} | {score.hits} | "
                     f"{score.hit_rate:.1%} | {score.lift:.2f}x |")

    lines += [
        "",
        f"The test period's base rate is {test_target.mean():.1%}, so calling "
        f"{options.call_budget} people at random yields about "
        f"{test_target.mean() * options.call_budget:.0f} subscriptions.",
        "",
        "Accuracy is deliberately not reported as a headline. At this base rate a model "
        "that predicts 'no' for everybody is "
        f"{1 - dataset['y'].eq('yes').mean():.1%} accurate and produces no call list.",
        "",
        "## What the leakage column would appear to buy",
        "",
        f"A second model trained on the same rows with `duration` included reaches "
        f"**{leaky.lift:.2f}x** within-month lift against the deployed model's "
        f"**{within_month['model'].lift:.2f}x**.",
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
        "train_rows": len(training_frame),
        "test_rows": len(split.test),
        "train_subscribe_rate": splits.subscribe_rate(training_frame),
        "test_subscribe_rate": splits.subscribe_rate(split.test),
        "within_month_model_lift": within_month["model"].lift,
        "within_month_model_worst": within_month["model"].worst_month_lift,
        "within_month_baseline_file_order_lift": within_month["baseline_file_order"].lift,
        "within_month_baseline_euribor_lift": within_month["baseline_euribor"].lift,
        "within_month_leaky_duration_lift": leaky.lift,
        "whole_period_model_lift": whole_period["model"].lift,
        "whole_period_baseline_file_order_lift": whole_period["baseline_file_order"].lift,
        "whole_period_baseline_euribor_lift": whole_period["baseline_euribor"].lift,
    }
    (options.out_dir / "bank-metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"\nwrote {options.out_dir / 'bank-training.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
