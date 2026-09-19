"""Run the bank contract against the real downloaded dataset.

Deliberately thin: the rules live in src/bank/contract.py so CI and the nightly job apply
the same ones. Anything more here would be a second copy, and second copies drift.

Proof that each rule fires when it should is in test_contract_catches_breakage.py.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.bank import contract

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    """The real campaign file."""
    if not DATASET.exists():
        pytest.skip(f"{DATASET} missing; run scripts/download_bank_data.py or `dvc pull`")
    return pd.read_csv(DATASET, sep=";")


def test_the_downloaded_dataset_satisfies_the_contract(dataset: pd.DataFrame) -> None:
    """The whole contract, against the whole file."""
    violations = contract.validate(dataset)
    assert violations == [], "\n".join(str(violation) for violation in violations)
