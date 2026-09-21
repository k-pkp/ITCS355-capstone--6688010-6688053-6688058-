"""Prove the within-month measurement does what it claims, including the failure it caught.

The project's central finding is that ranking a whole period and ranking one export are
different measurements, and that a column which is constant inside an export can win the
first while being worthless at the second. These tests pin that behaviour so a later
simplification of the block-splitting cannot quietly restore the old result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.bank import evaluate


def frame_with_months(month_sequence: list[str]) -> pd.DataFrame:
    """Build a frame carrying just the month column, in the given order."""
    return pd.DataFrame({"month": month_sequence})


def test_repeated_month_names_stay_separate_blocks():
    """May 2009 and May 2010 are different months and must not be merged.

    Grouping by the month *name* would put them in one block, which mixes two different
    interest-rate worlds and hands the ranking the cross-time comparison the measurement
    exists to remove.
    """
    frame = frame_with_months(["may"] * 3 + ["jun"] * 2 + ["may"] * 4)

    blocks = evaluate.contact_month_blocks(frame)

    assert [label for label, _ in blocks] == ["may", "jun", "may"]
    assert [len(positions) for _, positions in blocks] == [3, 2, 4]


def test_a_column_constant_within_months_scores_no_better_than_random():
    """The finding that changed the gate, as a test.

    One column takes a different value in each month and the same value inside each month.
    Ranked across the whole frame it sorts the months perfectly. Ranked inside a month it
    carries no information at all, and must come out at about 1.0.
    """
    rows_per_month = 400
    months = []
    monthly_value = []
    outcomes = []

    rng = np.random.default_rng(20260101)
    for month_index, month_name in enumerate(["jan", "feb", "mar", "apr"]):
        months += [month_name] * rows_per_month
        monthly_value += [10.0 - month_index] * rows_per_month
        # Later months subscribe more, exactly as the real campaign does.
        subscribe_rate = 0.05 + 0.10 * month_index
        outcomes += list(rng.binomial(1, subscribe_rate, rows_per_month))

    frame = frame_with_months(months)
    scores = -np.array(monthly_value)
    outcome_array = np.array(outcomes)

    across_the_period = evaluate.score_ranking(scores, outcome_array, call_budget=500)
    within_months = evaluate.score_within_contact_months(scores, outcome_array, frame)

    assert across_the_period.lift > 1.5, "sorting the calendar should look excellent"
    assert 0.8 < within_months.lift < 1.2, (
        "inside one month the column separates nobody, so it must score like random"
    )


def test_a_genuinely_informative_score_survives_both_measurements():
    """A score that ranks customers within their own month keeps its lift."""
    rows_per_month = 400
    rng = np.random.default_rng(20260102)

    months = []
    scores = []
    outcomes = []
    for month_name in ["jan", "feb", "mar", "apr"]:
        months += [month_name] * rows_per_month
        month_scores = rng.uniform(size=rows_per_month)
        scores += list(month_scores)
        # Subscribing depends on the score itself, so the ranking is genuinely useful.
        outcomes += list(rng.binomial(1, 0.05 + 0.5 * month_scores))

    within_months = evaluate.score_within_contact_months(
        np.array(scores), np.array(outcomes), frame_with_months(months))

    assert within_months.lift > 1.5
    assert within_months.worst_month_lift > 1.0


def test_small_month_blocks_are_dropped_rather_than_averaged_in():
    """A block of a few dozen rows is noise and must not be weighted like a real month."""
    months = ["jan"] * 400 + ["feb"] * 20
    rng = np.random.default_rng(20260103)
    scores = rng.uniform(size=len(months))
    outcomes = rng.binomial(1, 0.2, len(months))

    within_months = evaluate.score_within_contact_months(
        scores, outcomes, frame_with_months(months))

    assert within_months.month_labels == ["jan"]


def test_measuring_nothing_raises_rather_than_reporting_a_number():
    """With no block big enough, the answer is an error, not a confident lift.

    Returning 0.0 or 1.0 here would hand the gate a number it would compare against a
    threshold, and a gate comparing against a fabricated measurement is worse than one
    that stops.
    """
    months = ["jan"] * 50
    scores = np.linspace(0, 1, len(months))
    outcomes = np.ones(len(months), dtype=int)

    with pytest.raises(ValueError, match="nothing to measure"):
        evaluate.score_within_contact_months(scores, outcomes, frame_with_months(months))
