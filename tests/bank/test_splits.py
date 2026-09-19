"""Guard the time-ordered split against the shuffle that would look better.

On this dataset a random split reports halves that differ by 0.3 percentage points and a
time-ordered split reports halves that differ by a factor of 3.8. The wrong method is the
one that produces the reassuring number, so the prohibition cannot live in a comment.

These tests run against the real file, because the property being defended is a property of
that file's ordering. A synthetic fixture would pass whether or not the split function ever
touched real data.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.bank import splits

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    """The real campaign file, in its stored order."""
    if not DATASET.exists():
        pytest.skip(f"{DATASET} missing; run scripts/download_bank_data.py or `dvc pull`")
    return pd.read_csv(DATASET, sep=";")


def test_the_split_covers_every_row_exactly_once(dataset: pd.DataFrame) -> None:
    """No row may be lost, and none may appear in two parts."""
    split = splits.split_by_time(dataset)
    total = len(split.train) + len(split.validation) + len(split.test)
    assert total == len(dataset), f"{len(dataset) - total} rows went missing"


def test_the_parts_stay_in_chronological_order(dataset: pd.DataFrame) -> None:
    """Training data must come before validation, which must come before test.

    Checked through the index rather than a timestamp, because the dataset has no
    timestamp column: stored order is the only time information it carries.
    """
    split = splits.split_by_time(dataset)
    assert split.train.index.max() < split.validation.index.min()
    assert split.validation.index.max() < split.test.index.min()


def test_the_split_does_not_shuffle(dataset: pd.DataFrame) -> None:
    """Each part must still be in ascending order, exactly as stored."""
    split = splits.split_by_time(dataset)
    for name, part in (("train", split.train),
                       ("validation", split.validation),
                       ("test", split.test)):
        assert part.index.is_monotonic_increasing, f"{name} was reordered"


def test_the_time_split_exposes_the_distribution_shift(dataset: pd.DataFrame) -> None:
    """Train and test must differ substantially, because in this dataset they do.

    This is the test that would fail if someone replaced the split with a shuffle. It
    asserts the *presence* of a difference rather than its absence, which is unusual and
    is the point: on this file, halves that look alike are evidence of a bug.
    """
    split = splits.split_by_time(dataset)
    train_rate = splits.subscribe_rate(split.train)
    test_rate = splits.subscribe_rate(split.test)

    assert test_rate > train_rate * 2, (
        f"train {train_rate:.1%} and test {test_rate:.1%} are too similar. On this "
        f"dataset the campaign ran through the financial crisis and the subscribe rate "
        f"rises sharply, so similar halves mean the rows were shuffled."
    )


def test_a_shuffled_split_would_hide_the_shift(dataset: pd.DataFrame) -> None:
    """Demonstrate what the wrong method produces, so the difference is recorded.

    This test does not guard the code. It documents the trap with a number, so that
    anyone who proposes shuffling can see what it costs before doing it.
    """
    shuffled = dataset.sample(frac=1.0, random_state=20260101).reset_index(drop=True)
    halfway = len(shuffled) // 2
    first_rate = splits.subscribe_rate(shuffled.iloc[:halfway])
    second_rate = splits.subscribe_rate(shuffled.iloc[halfway:])

    assert abs(first_rate - second_rate) < 0.02, (
        "a random split is expected to produce near-identical halves on this dataset; "
        "if that is no longer true, this documentation test needs revisiting"
    )


def test_fractions_that_leave_no_test_set_are_rejected(dataset: pd.DataFrame) -> None:
    """Silently returning an empty test set would make every later metric meaningless."""
    with pytest.raises(ValueError):
        splits.split_by_time(dataset, train_fraction=0.8, validation_fraction=0.3)


def test_the_shift_description_reports_the_ratio(dataset: pd.DataFrame) -> None:
    """The training script prints this on every run, so it must say something true."""
    split = splits.split_by_time(dataset)
    description = splits.describe_shift(split)
    assert "subscribe rate" in description
    assert "x)" in description
