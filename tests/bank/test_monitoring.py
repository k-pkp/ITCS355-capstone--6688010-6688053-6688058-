"""Guard the drift detector, including the bug that made it report no drift at all.

A drift detector has one failure mode that matters more than the rest: silently returning
a low score for a column that moved. Nothing downstream can catch that, because a low score
is exactly what a healthy column produces.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.bank import monitoring


def make_series(values: list[float]) -> pd.Series:
    """Build a series for the detector to score."""
    return pd.Series(values, dtype=float)


def test_a_distribution_compared_with_itself_scores_about_zero() -> None:
    """The floor must be a real floor, or every score is inflated."""
    generator = np.random.default_rng(20260101)
    values = make_series(list(generator.normal(50, 10, 5000)))
    assert monitoring.population_stability_index(values, values) < 0.01


def test_a_resampled_window_stays_below_the_threshold() -> None:
    """Sampling noise alone must not trip the alert, or the alert is worthless."""
    generator = np.random.default_rng(20260101)
    reference = make_series(list(generator.normal(50, 10, 5000)))
    current = make_series(list(generator.normal(50, 10, 5000)))
    psi = monitoring.population_stability_index(reference, current)
    assert psi < monitoring.PSI_ALERT_THRESHOLD


def test_a_shifted_distribution_alerts() -> None:
    """A clear shift must cross the threshold."""
    generator = np.random.default_rng(20260101)
    reference = make_series(list(generator.normal(50, 10, 5000)))
    current = make_series(list(generator.normal(70, 10, 5000)))
    psi = monitoring.population_stability_index(reference, current)
    assert psi >= monitoring.PSI_ALERT_THRESHOLD


def test_a_low_cardinality_column_that_moved_is_not_reported_as_stable() -> None:
    """The regression test for the bug that reported nr.employed as perfectly stable.

    The real column holds three distinct values in the training window and seven in the
    held-out one, and the two ranges do not overlap at all — 5191-5228 against 4964-5099.
    The detector scored it 0.0000.

    The cause was bucket edges: three distinct values give two quantile edges, and the code
    overwrote both with infinities, leaving one bucket that contained everything. The fix
    adds the infinities as extra outer buckets instead of replacing real boundaries.
    """
    reference = make_series([5191.0] * 300 + [5228.1] * 700)
    current = make_series([4963.6] * 500 + [5076.2] * 500)

    psi = monitoring.population_stability_index(reference, current)
    assert psi >= monitoring.PSI_ALERT_THRESHOLD, (
        f"psi {psi:.4f}: a column whose reference and current ranges do not overlap "
        f"must not be reported as stable"
    )


def test_a_single_valued_reference_still_detects_a_move() -> None:
    """The most degenerate case: every reference row identical, current row different."""
    reference = make_series([100.0] * 1000)
    current = make_series([250.0] * 1000)
    psi = monitoring.population_stability_index(reference, current)
    assert psi >= monitoring.PSI_ALERT_THRESHOLD


def test_a_single_valued_column_that_did_not_move_scores_zero() -> None:
    """The mirror of the case above: unchanged must still read as unchanged."""
    reference = make_series([100.0] * 1000)
    current = make_series([100.0] * 1000)
    assert monitoring.population_stability_index(reference, current) < 0.01


def test_an_empty_window_does_not_raise() -> None:
    """A night with no rows is a run-metrics problem, not a drift calculation error."""
    reference = make_series([1.0, 2.0, 3.0])
    assert monitoring.population_stability_index(reference, make_series([])) == 0.0


def test_scores_come_back_worst_first() -> None:
    """The report lists the biggest mover at the top, so ordering is part of the contract."""
    generator = np.random.default_rng(20260101)
    reference = pd.DataFrame({
        "calm": generator.normal(50, 10, 2000),
        "moved": generator.normal(50, 10, 2000),
    })
    current = pd.DataFrame({
        "calm": generator.normal(50, 10, 2000),
        "moved": generator.normal(90, 10, 2000),
    })

    scores = monitoring.score_drift(reference, current, ("calm", "moved"))
    assert [score.column for score in scores] == ["moved", "calm"]


def test_a_missing_column_is_skipped_rather_than_crashing() -> None:
    """A column absent from one window must not take the whole check down."""
    frame = pd.DataFrame({"present": [1.0, 2.0, 3.0]})
    scores = monitoring.score_drift(frame, frame, ("present", "absent"))
    assert [score.column for score in scores] == ["present"]
