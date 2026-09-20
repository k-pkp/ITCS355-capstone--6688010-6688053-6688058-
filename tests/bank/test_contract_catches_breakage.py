"""Prove every bank contract rule fires when the thing it guards against happens.

A contract only ever run against good data is untested: it passes, and nobody knows whether
that is because the data is sound or because the rule is inert. Both look like a green
suite.

Each test takes a clean frame, breaks it in exactly one way, and asserts the matching rule
reports it.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.bank import contract


def make_clean_frame(row_count: int = 200) -> pd.DataFrame:
    """Build a frame that satisfies every rule, as the starting point for breaking it.

    Synthetic rather than a slice of the real file: a fixture built from real rows would
    start failing whenever the dataset changed, and these tests are about the rules.
    """
    rows = []
    for index in range(row_count):
        rows.append({
            "age": 25 + (index % 50),
            "job": "technician",
            "marital": "married",
            "education": "university.degree",
            "default": "no",
            "housing": "yes",
            "loan": "no",
            "contact": "cellular",
            "month": "may",
            "day_of_week": "mon",
            "duration": 100 + index,
            "campaign": 1 + (index % 3),
            "pdays": contract.PDAYS_NEVER_CONTACTED,
            "previous": 0,
            "poutcome": "nonexistent",
            "emp.var.rate": 1.1,
            "cons.price.idx": 93.994,
            "cons.conf.idx": -36.4,
            "euribor3m": 4.857,
            "nr.employed": 5191.0,
            "y": "yes" if index % 9 == 0 else "no",
        })
    return pd.DataFrame(rows)


@pytest.fixture()
def clean() -> pd.DataFrame:
    """A frame that must pass everything."""
    return make_clean_frame()


def rules_broken(violations: list[contract.Violation]) -> set[str]:
    """The set of rule names reported, for readable assertions."""
    return {violation.rule for violation in violations}


def test_clean_data_reports_no_violations(clean: pd.DataFrame) -> None:
    """The starting point must be genuinely clean, or every test below proves nothing."""
    violations = contract.validate(clean)
    assert violations == [], [str(violation) for violation in violations]


def test_a_dropped_column_is_caught(clean: pd.DataFrame) -> None:
    """The export renames or removes a field."""
    broken = clean.drop(columns=["euribor3m"])
    assert "required_columns" in rules_broken(contract.validate(broken))


def test_an_unexpected_target_value_is_caught(clean: pd.DataFrame) -> None:
    """The outcome column gains a third value, such as a pending state."""
    broken = clean.copy()
    broken.loc[3, "y"] = "pending"
    assert "unexpected_target_value" in rules_broken(contract.validate(broken))


def test_a_new_category_is_caught(clean: pd.DataFrame) -> None:
    """The quietest failure: a valid string the model has never seen.

    Nothing errors. A slice of customers is simply scored from a category that did not
    exist during training.
    """
    broken = clean.copy()
    broken.loc[5, "job"] = "influencer"
    assert "unexpected_category" in rules_broken(contract.validate(broken))


def test_a_renamed_category_is_caught(clean: pd.DataFrame) -> None:
    """An upstream tidy-up renames a category, which reads as a new one here."""
    broken = clean.copy()
    broken.loc[7, "education"] = "University Degree"
    assert "unexpected_category" in rules_broken(contract.validate(broken))


def test_an_implausible_age_is_caught(clean: pd.DataFrame) -> None:
    """The age column starts carrying something that is not an age."""
    broken = clean.copy()
    broken.loc[9, "age"] = 1975
    assert "implausible_age" in rules_broken(contract.validate(broken))


def test_a_null_is_caught(clean: pd.DataFrame) -> None:
    """The export changes how it represents an unknown, from a string to a null."""
    broken = clean.copy()
    broken.loc[11, "job"] = None
    assert "unexpected_null" in rules_broken(contract.validate(broken))


def test_an_ambiguous_pdays_is_caught(clean: pd.DataFrame) -> None:
    """A large pdays that is not the sentinel means the sentinel's meaning has changed."""
    broken = clean.copy()
    broken.loc[13, "pdays"] = 700
    assert "ambiguous_pdays" in rules_broken(contract.validate(broken))


def test_the_sentinel_itself_is_not_flagged(clean: pd.DataFrame) -> None:
    """999 is the documented sentinel and must not be reported as an error.

    96.3% of real rows carry it. A rule that flagged it would fire on almost every row of
    a healthy file, and would be switched off within a day.
    """
    assert "ambiguous_pdays" not in rules_broken(contract.validate(clean))


def test_a_zero_campaign_count_is_caught(clean: pd.DataFrame) -> None:
    """A customer contacted zero times during this campaign is not in this campaign."""
    broken = clean.copy()
    broken.loc[15, "campaign"] = 0
    assert "non_positive_campaign_count" in rules_broken(contract.validate(broken))


def test_several_breakages_are_all_reported_at_once(clean: pd.DataFrame) -> None:
    """Validation must not stop at the first problem.

    An export that broke in three ways should take one afternoon to diagnose, not three
    builds. This is easy to lose in a refactor that swaps the loop for an early return.
    """
    broken = clean.copy()
    broken.loc[1, "y"] = "maybe"
    broken.loc[2, "marital"] = "complicated"
    broken.loc[3, "age"] = -5

    reported = rules_broken(contract.validate(broken))
    assert {"unexpected_target_value", "unexpected_category",
            "implausible_age"} <= reported


def test_an_empty_export_is_caught(clean: pd.DataFrame) -> None:
    """An export that ran and produced nothing must be refused with a readable reason.

    Before this rule existed the empty frame reached the model, which raised a library
    error about array shapes: a stack trace that says nothing about the export having
    failed, arriving at 06:00 for whoever is on call.
    """
    assert "empty_input" in rules_broken(contract.validate(clean.head(0)))


def test_a_normal_frame_is_not_reported_as_empty(clean: pd.DataFrame) -> None:
    """The mirror: a frame with rows must never trip the empty check."""
    assert "empty_input" not in rules_broken(contract.validate(clean))
