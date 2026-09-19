"""What the nightly job reports about itself, and what drift looks like here.

Two separate jobs, kept apart on purpose.

**Run metrics** describe the job: rows in, rows published, how long it took, whether a gate
refused. These answer "did tonight work", and they are what an alert fires on.

**Drift** describes the world: how far tonight's customers differ from the ones the model
was trained on. This answers "is the model still the right model", and it must never fire
the same alert as the first kind. A run that refused to publish and a world that moved need
different people doing different things, and an alert that means either one means neither.

The drift measure is PSI, carried over from Lab 4 along with the finding that matters most
about it: **PSI measures how far the input moved, not how much the model minds.** In Lab 4 a
shift scoring 0.383 cost 0.0100 ROC AUC while one scoring 0.2627 cost 0.0167. So PSI opens
an investigation; it does not rank incidents.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# From Lab 4, where the threshold was set by measuring the noise floor of an unchanged
# window against the reference. Below this, the number is the window size talking.
PSI_ALERT_THRESHOLD = 0.20

# Bucket count for the distribution comparison. Ten is conventional and, more usefully,
# coarse enough that a few hundred rows still fill the buckets.
PSI_BUCKETS = 10


@dataclass(frozen=True)
class DriftScore:
    """How far one column moved between the reference window and tonight's."""

    column: str
    psi: float

    @property
    def alerts(self) -> bool:
        """Whether this score crosses the threshold that opens an investigation."""
        return self.psi >= PSI_ALERT_THRESHOLD

    def __str__(self) -> str:
        """Render the score for a report."""
        verdict = "ALERT" if self.alerts else "stable"
        return f"{self.column:<20} psi {self.psi:.4f}  {verdict}"


def bucket_edges_from_reference(reference_values: np.ndarray,
                                buckets: int) -> np.ndarray:
    """Return interior bucket boundaries derived from the reference window.

    Quantiles are the right tool for a column with many distinct values and the wrong one
    for a column with few. `nr.employed` holds three values in the training window: its
    quantile edges collapse, and whichever boundary survives leaves the moved data sharing
    a bucket with the reference.

    So a low-cardinality column is bucketed by the midpoints between its distinct values
    instead, which puts a boundary between each one. A column holding a single value gets
    a narrow band around it, so that anything else at all falls outside.
    """
    distinct = np.unique(reference_values)

    if len(distinct) > buckets:
        quantiles = np.linspace(0, 100, buckets + 1)
        return np.unique(np.percentile(reference_values, quantiles))

    if len(distinct) == 1:
        value = distinct[0]
        band = max(abs(value) * 1e-6, 1e-6)
        return np.array([value - band, value + band])

    return (distinct[:-1] + distinct[1:]) / 2


def population_stability_index(reference: pd.Series, current: pd.Series,
                               buckets: int = PSI_BUCKETS) -> float:
    """Return the PSI between two numeric distributions.

    Bucket edges come from the reference, never from the combined data. Deriving them from
    both would let tonight's window move the boundaries it is being measured against, which
    quietly shrinks every score toward zero — a drift detector that reports less drift the
    more the data drifts.
    """
    reference_values = reference.dropna().to_numpy(dtype=float)
    current_values = current.dropna().to_numpy(dtype=float)
    if len(reference_values) == 0 or len(current_values) == 0:
        return 0.0

    interior_edges = bucket_edges_from_reference(reference_values, buckets)

    # Open the outermost buckets by *adding* infinities rather than overwriting the first
    # and last edges. Overwriting them destroys real boundaries, and on a column with few
    # distinct values it destroys all of them: `nr.employed` has three values in the
    # reference window, so its edges collapsed to two, both were replaced, and every row
    # landed in a single bucket. The column had moved so far that its reference and
    # current ranges do not overlap at all, and the detector reported a PSI of exactly
    # zero. A drift detector that silently returns "no drift" is worse than none.
    edges = np.concatenate(([-np.inf], interior_edges, [np.inf]))

    reference_counts, _ = np.histogram(reference_values, bins=edges)
    current_counts, _ = np.histogram(current_values, bins=edges)

    # A zero in either bucket makes the logarithm infinite, so both are floored at a
    # proportion small enough not to matter and large enough to stay finite.
    floor = 1e-6
    reference_share = np.maximum(reference_counts / reference_counts.sum(), floor)
    current_share = np.maximum(current_counts / current_counts.sum(), floor)

    return float(np.sum((current_share - reference_share)
                        * np.log(current_share / reference_share)))


def score_drift(reference: pd.DataFrame, current: pd.DataFrame,
                columns: tuple[str, ...]) -> list[DriftScore]:
    """Score every named column, worst first."""
    scores = []
    for column in columns:
        if column not in reference.columns or column not in current.columns:
            continue
        scores.append(DriftScore(
            column=column,
            psi=population_stability_index(reference[column], current[column]),
        ))

    return sorted(scores, key=lambda score: score.psi, reverse=True)


def summarise_run(metrics: dict) -> list[str]:
    """Turn one night's run metrics into the lines a dashboard panel would show."""
    lines = [
        f"published: {metrics.get('published')}",
        f"rows in: {metrics.get('rows_in')}",
        f"rows published: {metrics.get('rows_published')}",
        f"input age (hours): {metrics.get('input_age_hours')}",
        f"duration (seconds): {metrics.get('duration_seconds')}",
    ]
    if metrics.get("refusal_reason"):
        lines.append(f"refused because: {metrics['refusal_reason']}")
    return lines
