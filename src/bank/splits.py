"""Splitting the dataset for training, and refusing to do it the way that looks fine.

The rows are stored in the order the calls were made, May 2008 to November 2010. That order
is the only time information the dataset has — there is no timestamp column — so it is the
only thing that can keep the validation set in the model's future.

Why this file exists rather than a one-line call to `train_test_split`: on this dataset the
wrong method produces the more reassuring result. Measured over the whole file:

    random 50/50 split        11.4% subscribe  vs  11.1% subscribe
    time-ordered 50/50 split   4.7% subscribe  vs  17.9% subscribe

A random split reports two nearly identical halves, validates beautifully, and has silently
told the model about the financial crisis before it happened. The time-ordered split reports
halves that differ by a factor of 3.8, which looks like a problem and is in fact the truth.

Anyone reaching for a shuffle here would see better numbers and no warning, which is exactly
why the prohibition is enforced by a test rather than written in a comment.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Split:
    """One train/validation/test division, with the proportions that produced it."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame

    def describe(self) -> str:
        """Summarise the split for a log or a report."""
        return (f"train {len(self.train):,} · "
                f"validation {len(self.validation):,} · "
                f"test {len(self.test):,}")


def split_by_time(frame: pd.DataFrame,
                  train_fraction: float = 0.6,
                  validation_fraction: float = 0.2) -> Split:
    """Divide the dataset in stored order: earliest rows train, latest rows test.

    The frame is never shuffled and never sorted. It arrives in campaign order, and any
    reordering here would destroy the only time signal the dataset carries.
    """
    if not 0 < train_fraction < 1:
        raise ValueError(f"train_fraction must be between 0 and 1, got {train_fraction}")
    if not 0 < validation_fraction < 1:
        raise ValueError(
            f"validation_fraction must be between 0 and 1, got {validation_fraction}"
        )
    if train_fraction + validation_fraction >= 1:
        raise ValueError(
            f"train_fraction + validation_fraction must leave room for a test set, "
            f"got {train_fraction} + {validation_fraction}"
        )

    row_count = len(frame)
    train_end = int(row_count * train_fraction)
    validation_end = train_end + int(row_count * validation_fraction)

    return Split(
        train=frame.iloc[:train_end].copy(),
        validation=frame.iloc[train_end:validation_end].copy(),
        test=frame.iloc[validation_end:].copy(),
    )


def subscribe_rate(frame: pd.DataFrame, target_column: str = "y") -> float:
    """Return the proportion of rows whose outcome is a subscription."""
    if frame.empty:
        return 0.0
    return float((frame[target_column] == "yes").mean())


def describe_shift(split: Split, target_column: str = "y") -> str:
    """Report how far the outcome rate moves between train and test.

    Printed by the training script on every run. A split whose halves look identical on
    this dataset is a split that was shuffled, and seeing the number every time is cheaper
    than remembering the rule.
    """
    train_rate = subscribe_rate(split.train, target_column)
    test_rate = subscribe_rate(split.test, target_column)
    ratio = (test_rate / train_rate) if train_rate else float("inf")

    return (f"subscribe rate: train {train_rate:.1%} -> test {test_rate:.1%} "
            f"({ratio:.1f}x). A ratio near 1.0 on this dataset means the rows were "
            f"shuffled and the split is invalid.")
