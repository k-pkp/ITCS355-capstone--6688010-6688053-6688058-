"""Scoring a ranked call list, and the baselines it has to beat.

Accuracy is the wrong measure here and reporting it would be misleading. The base rate is
11.3%, so a model that predicts "no" for every customer is 88.7% accurate and produces no
call list at all.

What the supervisor actually does is call down the list until the day runs out. So the
measure is: **of the first N customers we call, how many subscribe.** That is `hits_at`
below, and `lift_at` expresses it as a multiple of calling N people at random, which is what
happens today.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# The supervisor's working day, in calls. The figure the project reports is lift at this
# depth, because a model that ranks brilliantly below the point anyone reaches has not
# helped anybody.
DEFAULT_CALL_BUDGET = 500


@dataclass(frozen=True)
class RankingScore:
    """How a ranking performed at one call budget."""

    call_budget: int
    hits: int
    hit_rate: float
    baseline_hits: float
    lift: float

    def __str__(self) -> str:
        """Render the score as a line for a report."""
        return (f"top {self.call_budget}: {self.hits} subscriptions "
                f"({self.hit_rate:.1%}), against {self.baseline_hits:.0f} by calling at "
                f"random — lift {self.lift:.2f}x")


def hits_at(scores: np.ndarray, outcomes: np.ndarray, call_budget: int) -> int:
    """Count subscriptions among the highest-scoring `call_budget` customers."""
    if call_budget <= 0:
        raise ValueError(f"call_budget must be positive, got {call_budget}")

    budget = min(call_budget, len(scores))
    # argsort ascending, so the last `budget` entries are the highest scores.
    ranked_indices = np.argsort(scores)[-budget:]
    return int(outcomes[ranked_indices].sum())


def score_ranking(scores: np.ndarray, outcomes: np.ndarray,
                  call_budget: int = DEFAULT_CALL_BUDGET) -> RankingScore:
    """Score one ranking against calling the same number of people at random."""
    budget = min(call_budget, len(scores))
    hits = hits_at(scores, outcomes, budget)
    base_rate = float(outcomes.mean())
    baseline_hits = base_rate * budget

    return RankingScore(
        call_budget=budget,
        hits=hits,
        hit_rate=hits / budget if budget else 0.0,
        baseline_hits=baseline_hits,
        lift=(hits / baseline_hits) if baseline_hits else float("inf"),
    )


def baseline_file_order(frame: pd.DataFrame) -> np.ndarray:
    """Score customers by the order they appear in, which is what happens with no model.

    Descending, so the first row in the file is called first.
    """
    return np.arange(len(frame), 0, -1, dtype=float)


def baseline_single_column(frame: pd.DataFrame,
                           column: str = "euribor3m") -> np.ndarray:
    """Score customers by one column, as a spreadsheet would.

    Euribor is the strongest single number in this dataset, because it tracks the period
    when subscriptions were easiest.

    How hard a baseline that is depends entirely on how it is measured, and the difference
    is the largest single finding in this project. Ranked across the whole test period at
    once it reaches 1.80x lift and beats the model. Ranked inside single contact months --
    which is what the deployed job does -- it reaches 0.96x, no better than calling people
    in no particular order, because euribor moves between months and barely moves within
    one. The first measurement was scoring it on its ability to sort the calendar.

    See `score_within_contact_months` and reports/bank-export-evaluation.md.
    """
    values = frame[column].to_numpy(dtype=float)
    # Low Euribor coincided with high subscription rates, so invert it into a score.
    return -values


# The supervisor's day, as a share of one export. 500 calls out of an export of about 3,000
# customers. Expressed as a share so the same measurement works on a month with 3,275 rows
# and one with 212.
CALL_SHARE_OF_EXPORT = 500 / 3000

# Month blocks smaller than this are dropped from the measurement. A block of forty rows
# produces a lift computed from two or three subscriptions, which is noise with a decimal
# point on it.
MINIMUM_BLOCK_ROWS = 200


@dataclass(frozen=True)
class WithinMonthScore:
    """How a ranking performed inside single months, rather than across the whole period.

    `lift` is the row-weighted mean across months, so it can be compared against a
    RankingScore's lift and handed to the gate unchanged.
    """

    lift: float
    month_lifts: list[float]
    month_labels: list[str]
    month_rows: list[int]

    @property
    def worst_month_lift(self) -> float:
        """The weakest month, which is what a bad month actually costs the call centre."""
        return min(self.month_lifts) if self.month_lifts else float("nan")

    def __str__(self) -> str:
        """Render the score as a line for a report."""
        return (f"within month: lift {self.lift:.2f}x across {len(self.month_lifts)} "
                f"months, worst month {self.worst_month_lift:.2f}x")


def contact_month_blocks(frame: pd.DataFrame,
                         month_column: str = "month") -> list[tuple[str, np.ndarray]]:
    """Split a frame into consecutive runs of rows sharing one contact month.

    The rows are in campaign order and carry no date, so a run of rows with the same month
    value is the closest thing the dataset has to "the calls made during one stretch of
    time". The same month name appears more than once across the campaign's two and a half
    years, and each appearance is its own block -- grouping by the name would merge May 2009
    with May 2010, which are different interest-rate worlds.
    """
    month_values = frame[month_column].to_numpy()
    blocks = []
    block_start = 0

    for position in range(1, len(month_values) + 1):
        reached_end = position == len(month_values)
        if reached_end or month_values[position] != month_values[block_start]:
            blocks.append((str(month_values[block_start]),
                           np.arange(block_start, position)))
            block_start = position

    return blocks


def score_within_contact_months(scores: np.ndarray, outcomes: np.ndarray,
                                frame: pd.DataFrame) -> WithinMonthScore:
    """Score a ranking the way the deployed job is judged: one month's calls at a time.

    Measuring across the whole period asks a question the deployed job is never asked. The
    job receives one export and decides who in *that export* to call first. It is never
    asked to decide between a customer contacted in 2008 and one contacted in 2010, and any
    ranking that scores well only by making that comparison has earned its score from
    information it will not have.

    This matters here rather than being a technicality: ranking the whole test period by
    `euribor3m` reaches 1.80x lift, and inside single months the same column reaches 0.96x,
    which is no better than calling people in no particular order. Euribor moves between
    months and barely moves within one, so the whole-period measurement was scoring it on
    its ability to sort the calendar.
    """
    lifts = []
    labels = []
    row_counts = []

    for month_label, positions in contact_month_blocks(frame):
        block_outcomes = outcomes[positions]
        too_small = len(positions) < MINIMUM_BLOCK_ROWS
        no_subscriptions = block_outcomes.sum() == 0
        if too_small or no_subscriptions:
            continue

        call_budget = max(10, int(len(positions) * CALL_SHARE_OF_EXPORT))
        block_score = score_ranking(scores[positions], block_outcomes, call_budget)

        lifts.append(block_score.lift)
        labels.append(month_label)
        row_counts.append(len(positions))

    if not lifts:
        raise ValueError(
            f"no month block had at least {MINIMUM_BLOCK_ROWS} rows and one subscription, "
            f"so there is nothing to measure"
        )

    weighted_lift = float(np.average(lifts, weights=row_counts))
    return WithinMonthScore(lift=weighted_lift, month_lifts=lifts,
                            month_labels=labels, month_rows=row_counts)
