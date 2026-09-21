"""What connects an approved model to the model that actually runs.

The gate decides whether a model *may* be promoted. Nothing in this project previously
decided what *is* promoted: the nightly job loaded whichever file happened to be at
`reports/bank-model.joblib`, and the image was built from whatever was on disk at build
time. So "which model is in production" was answered by a build log rather than by a check,
and swapping the file would have changed every published call list with nothing objecting.

This module closes that gap with one idea: **the approved model is identified by the hash
of its bytes, and the serving job refuses to run a model whose bytes do not match.**

A hash rather than a version number, because a version number is a label someone writes and
a hash is a fact about the file. Lab 5 pushed the same image tag three times in one
afternoon and ended up with a tag naming code that was not inside the image; the same thing
happens to a model called "v1".
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Approval:
    """The record of which model the gate approved, written at registration time."""

    model_sha256: str
    registered_version: str
    metric_lift: float
    registered_at_utc: str

    def as_dict(self) -> dict:
        """Render the approval for writing to disk."""
        return {
            "model_sha256": self.model_sha256,
            "registered_version": self.registered_version,
            "metric_lift": self.metric_lift,
            "registered_at_utc": self.registered_at_utc,
        }


class UnapprovedModelError(RuntimeError):
    """Raised when the model on disk is not the model the gate approved."""


def hash_file(path: Path) -> str:
    """Return the SHA-256 of a file's bytes.

    Read in chunks rather than all at once. A model file is small today and the function
    should not acquire a size limit by accident.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_approval(path: Path, approval: Approval) -> None:
    """Record which model bytes were approved, for the serving job to check against."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(approval.as_dict(), indent=2) + "\n")


def read_approval(path: Path) -> Approval | None:
    """Return the recorded approval, or None if nothing has ever been approved.

    None is returned rather than an empty Approval, so that "no model has been approved"
    and "a model was approved and its hash is blank" cannot be confused by a caller.
    """
    if not path.exists():
        return None

    record = json.loads(path.read_text())
    return Approval(
        model_sha256=record["model_sha256"],
        registered_version=str(record["registered_version"]),
        metric_lift=float(record["metric_lift"]),
        registered_at_utc=str(record["registered_at_utc"]),
    )


def require_approved_model(model_path: Path, approval_path: Path) -> str:
    """Refuse to serve a model whose bytes are not the approved ones.

    Returns the hash on success, so the caller can log what it verified rather than log
    that it verified something.

    This raises rather than returning a decision, unlike the freshness gate. A stale input
    is an ordinary operational event that the job reports and exits on. A serving model
    that nobody approved is a different kind of event: it means the deployment pipeline
    put something in the image that the gate never saw, and continuing would publish a call
    list from an unknown model.
    """
    approval = read_approval(approval_path)
    if approval is None:
        raise UnapprovedModelError(
            f"no approval record at {approval_path}: no model has been through the gate, "
            f"so there is nothing that says this one may serve"
        )

    if not model_path.exists():
        raise UnapprovedModelError(f"no model at {model_path}")

    serving_hash = hash_file(model_path)
    if serving_hash != approval.model_sha256:
        raise UnapprovedModelError(
            f"the model at {model_path} is not the approved one.\n"
            f"  approved: {approval.model_sha256} (registered version "
            f"{approval.registered_version})\n"
            f"  serving:  {serving_hash}\n"
            f"The gate approved a model and the image contains a different one."
        )

    return serving_hash
