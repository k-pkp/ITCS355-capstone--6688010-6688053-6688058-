"""The data contract for the bank marketing dataset.

These rules describe what the customer export promises. They run in CI against the whole
dataset, and again in the nightly job against each incoming file, so the two cannot drift
apart.

Each check returns violations rather than raising. CI fails the build on any of them; the
nightly job decides per rule whether to stop or to carry on with fewer rows, because
refusing to produce a call list at all because one column gained one unexpected value would
be its own kind of outage.

A note on what is deliberately *not* here. Nothing in this file asks whether the data looks
like the data the model was trained on. That question is drift, it is answered in the
monitoring half of the project, and it has a different answer: a contract violation means
the export is broken and someone must fix it, while drift means the world changed and the
model must be retrained. Mixing them produces a gate that fires for two unrelated reasons
and is therefore ignored for both.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

TARGET_COLUMN = "y"
TARGET_VALUES = frozenset({"yes", "no"})

# The sentinel pdays uses for "this customer was never previously contacted". It is not a
# number of days, and 96.3% of rows carry it.
PDAYS_NEVER_CONTACTED = 999

REQUIRED_COLUMNS = (
    "age", "job", "marital", "education", "default", "housing", "loan",
    "contact", "month", "day_of_week", "duration", "campaign", "pdays",
    "previous", "poutcome", "emp.var.rate", "cons.price.idx", "cons.conf.idx",
    "euribor3m", "nr.employed", TARGET_COLUMN,
)

# Columns whose values come from a fixed vocabulary. An unexpected value is a valid string
# that the model has never seen, which is the quietest kind of upstream change: nothing
# errors, and a slice of customers is scored from a category that did not exist in training.
CATEGORICAL_VOCABULARIES = {
    "job": {"admin.", "blue-collar", "entrepreneur", "housemaid", "management",
            "retired", "self-employed", "services", "student", "technician",
            "unemployed", "unknown"},
    "marital": {"divorced", "married", "single", "unknown"},
    "education": {"basic.4y", "basic.6y", "basic.9y", "high.school", "illiterate",
                  "professional.course", "university.degree", "unknown"},
    "default": {"no", "yes", "unknown"},
    "housing": {"no", "yes", "unknown"},
    "loan": {"no", "yes", "unknown"},
    "contact": {"cellular", "telephone"},
    "poutcome": {"failure", "nonexistent", "success"},
    "day_of_week": {"mon", "tue", "wed", "thu", "fri"},
    "month": {"jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"},
}

# A telephone campaign contacts adults. The bounds are wide on purpose: the job is to catch
# a column that has shifted meaning, not to argue about whether a 96-year-old was called.
MINIMUM_AGE = 17
MAXIMUM_AGE = 100


@dataclass(frozen=True)
class Violation:
    """One broken rule, with enough detail to act on without re-running anything."""

    rule: str
    detail: str
    row_count: int

    def __str__(self) -> str:
        """Render the violation the way it appears in CI output."""
        return f"{self.rule}: {self.detail} ({self.row_count} rows)"


def check_required_columns(frame: pd.DataFrame) -> list[Violation]:
    """Every column the pipeline reads must be present."""
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if not missing:
        return []
    return [Violation("required_columns", f"missing {missing}", len(frame))]


def check_target_values(frame: pd.DataFrame) -> list[Violation]:
    """The outcome column must only ever hold the two values it is defined to hold."""
    if TARGET_COLUMN not in frame.columns:
        return []

    unexpected = set(frame[TARGET_COLUMN].dropna().unique()) - TARGET_VALUES
    if not unexpected:
        return []
    return [Violation(
        "unexpected_target_value",
        f"expected only {sorted(TARGET_VALUES)}, found {sorted(unexpected)}",
        int(frame[TARGET_COLUMN].isin(unexpected).sum()),
    )]


def check_categorical_vocabularies(frame: pd.DataFrame) -> list[Violation]:
    """Categorical columns must stay inside their known vocabulary.

    This is the rule most likely to earn its place. An export that starts writing a new
    category, or renames one, produces valid strings that break nothing and silently score
    a slice of customers from a category the model never learned.
    """
    violations = []
    for column, vocabulary in CATEGORICAL_VOCABULARIES.items():
        if column not in frame.columns:
            continue

        present = set(frame[column].dropna().unique())
        unexpected = present - vocabulary
        if unexpected:
            violations.append(Violation(
                "unexpected_category",
                f"{column} contains {sorted(unexpected)}, which is not in its vocabulary",
                int(frame[column].isin(unexpected).sum()),
            ))
    return violations


def check_age_is_plausible(frame: pd.DataFrame) -> list[Violation]:
    """Age outside a wide human range means the column changed meaning, not that it is odd."""
    if "age" not in frame.columns:
        return []

    outside = (frame["age"] < MINIMUM_AGE) | (frame["age"] > MAXIMUM_AGE)
    count = int(outside.sum())
    if count == 0:
        return []
    return [Violation(
        "implausible_age",
        f"ages outside {MINIMUM_AGE}-{MAXIMUM_AGE}, "
        f"from {frame.loc[outside, 'age'].min()} to {frame.loc[outside, 'age'].max()}",
        count,
    )]


def check_no_missing_values(frame: pd.DataFrame) -> list[Violation]:
    """This dataset encodes unknowns as the string 'unknown', never as a null.

    A genuine null therefore means the export changed how it represents missing data, and
    every count and average computed downstream quietly changes meaning with it.
    """
    violations = []
    for column in frame.columns:
        missing_count = int(frame[column].isna().sum())
        if missing_count:
            violations.append(Violation(
                "unexpected_null",
                f"{column} has nulls; this dataset encodes unknowns as the string 'unknown'",
                missing_count,
            ))
    return violations


def check_pdays_sentinel(frame: pd.DataFrame) -> list[Violation]:
    """`pdays` must be the sentinel or a small number of days, never in between.

    999 means "never previously contacted". Real values in this dataset run 0 to 27. A value
    in the hundreds would mean the sentinel changed, or that someone has begun writing real
    long gaps, and either way every model treating 999 as a magic number becomes wrong
    without anything failing.
    """
    if "pdays" not in frame.columns:
        return []

    suspicious = (frame["pdays"] > 365) & (frame["pdays"] != PDAYS_NEVER_CONTACTED)
    count = int(suspicious.sum())
    if count == 0:
        return []
    return [Violation(
        "ambiguous_pdays",
        f"values above 365 that are not the {PDAYS_NEVER_CONTACTED} sentinel: "
        f"{sorted(frame.loc[suspicious, 'pdays'].unique())[:5]}",
        count,
    )]


def check_campaign_counts_are_positive(frame: pd.DataFrame) -> list[Violation]:
    """A customer contacted zero times during this campaign is not in this campaign."""
    if "campaign" not in frame.columns:
        return []

    invalid = frame["campaign"] < 1
    count = int(invalid.sum())
    if count == 0:
        return []
    return [Violation(
        "non_positive_campaign_count",
        f"campaign contact count below 1, lowest {frame['campaign'].min()}",
        count,
    )]


def validate(frame: pd.DataFrame) -> list[Violation]:
    """Run every rule and return everything that is wrong.

    All rules run even after one fails. An export that broke in three ways should take one
    afternoon to diagnose, not three builds.
    """
    violations: list[Violation] = []
    violations += check_required_columns(frame)
    violations += check_target_values(frame)
    violations += check_categorical_vocabularies(frame)
    violations += check_age_is_plausible(frame)
    violations += check_no_missing_values(frame)
    violations += check_pdays_sentinel(frame)
    violations += check_campaign_counts_are_positive(frame)
    return violations
