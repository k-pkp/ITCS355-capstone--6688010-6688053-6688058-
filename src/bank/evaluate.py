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
    when subscriptions were easiest. A model that cannot beat one column is not worth
    deploying, and this is a harder baseline than it looks.
    """
    values = frame[column].to_numpy(dtype=float)
    # Low Euribor coincided with high subscription rates, so invert it into a score.
    return -values
