"""Guard the feature builder against the two mistakes that do not raise an error.

Both are silent by nature. Including `duration` makes the model look better, not worse, so
nothing about the training run signals a problem. And one-hot columns derived from the data
produce a different shape for a different input, which surfaces at serving time as a
mismatch nobody can reproduce locally.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.bank import contract, features

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"


def make_clean_frame(row_count: int = 50) -> pd.DataFrame:
    """A small frame with every column the feature builder needs."""
    rows = []
    for index in range(row_count):
        rows.append({
            "age": 30 + (index % 40),
            "job": "technician",
            "marital": "married",
            "education": "university.degree",
            "default": "no",
            "housing": "yes",
            "loan": "no",
            "contact": "cellular",
            "month": "may",
            "day_of_week": "mon",
            "duration": 200 + index,
            "campaign": 1,
            "pdays": contract.PDAYS_NEVER_CONTACTED,
            "previous": 0,
            "poutcome": "nonexistent",
            "emp.var.rate": 1.1,
            "cons.price.idx": 93.994,
            "cons.conf.idx": -36.4,
            "euribor3m": 4.857,
            "nr.employed": 5191.0,
            "y": "no",
        })
    return pd.DataFrame(rows)


@pytest.fixture()
def clean() -> pd.DataFrame:
    """A frame the builder should handle without complaint."""
    return make_clean_frame()


def test_duration_never_reaches_the_model(clean: pd.DataFrame) -> None:
    """The leakage column must be absent from the built features.

    `duration` is the most predictive column in the dataset and is not known at prediction
    time. A model trained with it scores well and is worthless deployed. This test is the
    cheapest one in the project and the most valuable.
    """
    built = features.build_features(clean)
    assert "duration" not in built.columns
    assert not any("duration" in name for name in built.columns)


def test_the_target_never_reaches_the_model(clean: pd.DataFrame) -> None:
    """The answer must not appear among the questions."""
    built = features.build_features(clean)
    assert contract.TARGET_COLUMN not in built.columns


def test_the_columns_do_not_depend_on_the_input(clean: pd.DataFrame) -> None:
    """A frame containing fewer categories must still produce every column.

    This is the training/serving skew failure. Built from the data, a night's batch
    containing nine job categories would produce nine columns where the model expects
    twelve.
    """
    full = features.build_features(clean)

    narrow = clean.copy()
    narrow["job"] = "retired"
    narrow["month"] = "dec"
    narrow_built = features.build_features(narrow)

    assert list(full.columns) == list(narrow_built.columns)


def test_the_column_order_is_stable(clean: pd.DataFrame) -> None:
    """Position matters: a model reads columns by order, not by name."""
    first = features.build_features(clean)
    second = features.build_features(clean.iloc[::-1].copy())
    assert list(first.columns) == list(second.columns)


def test_feature_names_matches_what_is_built(clean: pd.DataFrame) -> None:
    """The advertised names must equal the produced ones.

    The serving side asserts its payload shape against feature_names() without loading a
    model, so the two drifting apart would break serving while training stayed green.
    """
    built = features.build_features(clean)
    assert features.feature_names() == list(built.columns)


def test_the_pdays_sentinel_does_not_reach_the_model(clean: pd.DataFrame) -> None:
    """999 must not appear as a number of days.

    Left raw, the model learns that a customer contacted 999 days ago behaves like one
    never contacted, which is true only by an accident of encoding.
    """
    built = features.build_features(clean)
    assert (built["days_since_previous_contact"] != contract.PDAYS_NEVER_CONTACTED).all()
    assert (built["was_previously_contacted"] == 0).all()


def test_a_previously_contacted_customer_keeps_their_day_count() -> None:
    """The real day counts must survive the transformation."""
    frame = make_clean_frame(row_count=3)
    frame.loc[1, "pdays"] = 6

    built = features.build_features(frame)
    assert built.loc[1, "was_previously_contacted"] == 1
    assert built.loc[1, "days_since_previous_contact"] == 6
    assert built.loc[0, "was_previously_contacted"] == 0


def test_a_missing_column_fails_loudly(clean: pd.DataFrame) -> None:
    """Building features from an incomplete frame must raise, not improvise."""
    with pytest.raises(ValueError, match="missing columns"):
        features.build_features(clean.drop(columns=["euribor3m"]))


def test_the_real_dataset_builds_without_error() -> None:
    """The builder must handle every row of the actual file."""
    if not DATASET.exists():
        pytest.skip(f"{DATASET} missing; run scripts/download_bank_data.py or `dvc pull`")

    dataset = pd.read_csv(DATASET, sep=";")
    built = features.build_features(dataset)

    assert len(built) == len(dataset)
    assert built.notna().all().all(), "features contain nulls"
    assert list(built.columns) == features.feature_names()
