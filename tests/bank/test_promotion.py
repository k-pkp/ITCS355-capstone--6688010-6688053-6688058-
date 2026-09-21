"""Prove the serving job cannot be handed a model nobody approved.

The gate deciding that a model may serve is worth nothing if a different file ships. These
tests pin the link between the two, including the case the link exists to catch: a model
file that is perfectly valid, loads without complaint, and is not the approved one.
"""
from __future__ import annotations

import json

import pytest

from src.bank import promotion


def write_model_file(path, contents: bytes):
    """Write some bytes standing in for a serialised model."""
    path.write_bytes(contents)
    return path


def approve(path, model_sha256: str):
    """Write an approval record naming the given hash."""
    promotion.write_approval(path, promotion.Approval(
        model_sha256=model_sha256,
        registered_version="1",
        metric_lift=1.34,
        registered_at_utc="2026-09-21T01:53:14+00:00",
    ))


def test_the_approved_model_is_accepted_and_its_hash_returned(tmp_path):
    """A matching model passes, and the hash it verified comes back for logging."""
    model_path = write_model_file(tmp_path / "model.joblib", b"the approved bytes")
    approval_path = tmp_path / "approved-model.json"
    approve(approval_path, promotion.hash_file(model_path))

    verified = promotion.require_approved_model(model_path, approval_path)

    assert verified == promotion.hash_file(model_path)


def test_a_different_model_is_refused_even_though_the_file_is_valid(tmp_path):
    """The failure this whole module exists for.

    Nothing is wrong with the substituted file. It would load, score and publish a call
    list. It is simply not the model the gate saw.
    """
    model_path = write_model_file(tmp_path / "model.joblib", b"the approved bytes")
    approval_path = tmp_path / "approved-model.json"
    approve(approval_path, promotion.hash_file(model_path))

    write_model_file(model_path, b"a different model, equally loadable")

    with pytest.raises(promotion.UnapprovedModelError, match="not the approved one"):
        promotion.require_approved_model(model_path, approval_path)


def test_no_approval_record_refuses_rather_than_serving_anything(tmp_path):
    """With nothing approved, the answer is a refusal, not a shrug.

    Treating a missing approval as "no rule, carry on" would make the check disappear
    exactly when it has never been set up, which is when it is needed most.
    """
    model_path = write_model_file(tmp_path / "model.joblib", b"some model")

    with pytest.raises(promotion.UnapprovedModelError, match="no approval record"):
        promotion.require_approved_model(model_path, tmp_path / "missing.json")


def test_a_missing_model_is_refused(tmp_path):
    """An approval with no model behind it is still a refusal."""
    approval_path = tmp_path / "approved-model.json"
    approve(approval_path, "0" * 64)

    with pytest.raises(promotion.UnapprovedModelError, match="no model at"):
        promotion.require_approved_model(tmp_path / "absent.joblib", approval_path)


def test_reading_a_missing_approval_returns_none_rather_than_an_empty_record(tmp_path):
    """None and a blank hash must not be confusable by a caller."""
    assert promotion.read_approval(tmp_path / "nothing.json") is None


def test_the_approval_survives_a_round_trip(tmp_path):
    """What is written is what is read back, field for field."""
    approval_path = tmp_path / "approved-model.json"
    original = promotion.Approval(
        model_sha256="a" * 64,
        registered_version="7",
        metric_lift=1.4012,
        registered_at_utc="2026-09-21T01:53:14+00:00",
    )
    promotion.write_approval(approval_path, original)

    assert promotion.read_approval(approval_path) == original
    assert json.loads(approval_path.read_text())["registered_version"] == "7"
