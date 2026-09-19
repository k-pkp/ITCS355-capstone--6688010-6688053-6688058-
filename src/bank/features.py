"""Turn campaign rows into the numbers the model sees.

Two decisions in this file are load-bearing, and both are about failures that do not raise
an error.

**`duration` is excluded.** It records how long the call lasted, correlates 0.405 with the
outcome, and is the single most predictive column in the dataset. It is also unusable: the
call has not happened when the list is scored. A model trained with it validates beautifully
and is worthless the moment it is deployed, because the feature simply is not there. This is
the dataset's famous trap, and the dataset's own documentation warns about it.

**The one-hot columns come from the contract's vocabularies, not from the data.** Building
them with `pd.get_dummies` produces whichever categories happen to appear in the frame being
processed. Training on a file containing all twelve job categories and then serving a
night's batch that happens to contain nine produces nine columns where the model expects
twelve — a silent shape mismatch, or worse, a quiet misalignment where a column of one name
lands in the position of another. Deriving the columns from a fixed vocabulary makes that
impossible: the same columns come out every time, in the same order, whatever the input
contains.
"""
from __future__ import annotations

import pandas as pd

from src.bank import contract

TARGET_COLUMN = contract.TARGET_COLUMN

# Excluded, with the reason, because a list of names with no explanation gets "tidied" back
# in by the next person who notices the model could score higher.
EXCLUDED_COLUMNS = {
    "duration": (
        "leakage: the call has not happened when the prediction is made. It correlates "
        "0.405 with the outcome, which is exactly why it is tempting."
    ),
    TARGET_COLUMN: "the answer",
}

NUMERIC_COLUMNS = (
    "age",
    "campaign",
    "previous",
    "emp.var.rate",
    "cons.price.idx",
    "cons.conf.idx",
    "euribor3m",
    "nr.employed",
)

CATEGORICAL_COLUMNS = (
    "job", "marital", "education", "default", "housing", "loan",
    "contact", "month", "day_of_week", "poutcome",
)

# `pdays` is not used directly. See split_previous_contact below.
DERIVED_COLUMNS = ("was_previously_contacted", "days_since_previous_contact")


def split_previous_contact(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn `pdays` into a flag and a number that each mean one thing.

    `pdays` holds 999 for "never previously contacted", which is 96.3% of rows, and a real
    number of days between 0 and 27 for the rest. A model given the raw column learns from
    a value that is a sentinel most of the time and a measurement occasionally, and nothing
    reports a problem: 999 is a perfectly good number, and the model will happily conclude
    that customers contacted a very long time ago behave like customers never contacted at
    all. Which is true here only by coincidence of encoding.

    So it becomes two columns. The flag carries the fact. The number carries the days, and
    is zero when the flag says there were none — a value the model can only reach through
    the flag, rather than a large number it has to learn to treat as special.
    """
    result = pd.DataFrame(index=frame.index)
    never_contacted = frame["pdays"] == contract.PDAYS_NEVER_CONTACTED

    result["was_previously_contacted"] = (~never_contacted).astype(int)
    result["days_since_previous_contact"] = frame["pdays"].where(~never_contacted, 0)
    return result


def one_hot_from_vocabulary(frame: pd.DataFrame) -> pd.DataFrame:
    """Encode categoricals against the fixed vocabulary, not against what arrived.

    Every column in the contract's vocabulary produces exactly one output column, whether
    or not that category appears in this frame. A category that arrives and is *not* in the
    vocabulary produces no column at all, and is caught by the contract rather than
    silently widening the feature space.
    """
    encoded = pd.DataFrame(index=frame.index)

    for column in CATEGORICAL_COLUMNS:
        vocabulary = sorted(contract.CATEGORICAL_VOCABULARIES[column])
        for value in vocabulary:
            encoded[f"{column}={value}"] = (frame[column] == value).astype(int)

    return encoded


def feature_names() -> list[str]:
    """Return every feature column, in the order build_features produces them.

    Computed from the vocabularies rather than from a trained model, so the serving side
    can assert the shape it is about to send without loading anything.
    """
    names = list(NUMERIC_COLUMNS) + list(DERIVED_COLUMNS)
    for column in CATEGORICAL_COLUMNS:
        for value in sorted(contract.CATEGORICAL_VOCABULARIES[column]):
            names.append(f"{column}={value}")
    return names


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Build the model's input matrix from raw campaign rows.

    The column order is fixed and does not depend on the input, so a frame scored tonight
    produces the same columns in the same positions as the frame the model was trained on.
    """
    missing = [column for column in NUMERIC_COLUMNS + CATEGORICAL_COLUMNS + ("pdays",)
               if column not in frame.columns]
    if missing:
        raise ValueError(
            f"cannot build features, missing columns: {missing}. The data contract should "
            f"have caught this before it reached here."
        )

    numeric = frame[list(NUMERIC_COLUMNS)].copy()
    derived = split_previous_contact(frame)
    categorical = one_hot_from_vocabulary(frame)

    features = pd.concat([numeric, derived, categorical], axis=1)
    return features[feature_names()]


def build_target(frame: pd.DataFrame) -> pd.Series:
    """Return the outcome as 1 for a subscription and 0 otherwise."""
    return (frame[TARGET_COLUMN] == "yes").astype(int)
