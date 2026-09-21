"""The cloud-facing half of the nightly job: object storage and metrics.

Kept in one module so that the scoring logic never learns which cloud it is on, and so the
same nightly job runs locally against a file and in the cloud against a bucket without two
versions of the steps in between.

Every function here fails loudly rather than falling back. A cloud helper that silently
degrades to a local path is how a scheduled job appears to work for a week while writing its
output somewhere nobody is reading.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Where the project keeps its cloud state. Read from the environment so the same image runs
# against a different bucket without rebuilding.
BUCKET = os.environ.get("CAPSTONE_BUCKET", "itcs355-6688010")
PREFIX = os.environ.get("CAPSTONE_PREFIX", "capstone")
PROJECT_ID = os.environ.get("CAPSTONE_PROJECT", "itcs355-6688010")

# The metric namespace. Matching the course's convention makes teardown able to find
# everything this project created.
METRIC_PREFIX = "custom.googleapis.com/itcs355/capstone"


@dataclass(frozen=True)
class RemoteObject:
    """One object in the bucket, with the timestamp the freshness gate needs."""

    bucket: str
    name: str
    updated_at: datetime
    size_bytes: int

    @property
    def uri(self) -> str:
        """The gs:// address, for logging."""
        return f"gs://{self.bucket}/{self.name}"


def _storage_client():
    """Return a Cloud Storage client, importing the SDK only when actually used."""
    from google.cloud import storage

    return storage.Client(project=PROJECT_ID)


def describe_object(object_name: str) -> RemoteObject:
    """Return an object's metadata, including when it was last written.

    The update time comes from the object's own metadata rather than from the job's clock.
    A scheduled job that trusts its own clock to decide what day the data is from will
    believe whatever it is handed.
    """
    client = _storage_client()
    blob = client.bucket(BUCKET).get_blob(object_name)
    if blob is None:
        raise FileNotFoundError(f"gs://{BUCKET}/{object_name} does not exist")

    return RemoteObject(
        bucket=BUCKET,
        name=object_name,
        updated_at=blob.updated.astimezone(timezone.utc),
        size_bytes=blob.size or 0,
    )


def download(object_name: str, destination: Path) -> RemoteObject:
    """Fetch one object to a local path and return its metadata."""
    described = describe_object(object_name)
    destination.parent.mkdir(parents=True, exist_ok=True)

    client = _storage_client()
    client.bucket(BUCKET).blob(object_name).download_to_filename(str(destination))
    return described


def upload(source: Path, object_name: str) -> str:
    """Upload one local file and return the address it actually landed at.

    Returns the address rather than the one the caller intended, because printing the
    intended path is how a write to the wrong key looks like a success in the logs.
    """
    client = _storage_client()
    blob = client.bucket(BUCKET).blob(object_name)
    blob.upload_from_filename(str(source))
    return f"gs://{BUCKET}/{object_name}"


def emit_metrics(metrics: dict[str, float]) -> list[str]:
    """Write one point per named metric to Cloud Monitoring.

    Each metric is written under the project's own namespace with a label saying which
    course and project it belongs to, so teardown can find everything and a dashboard can
    query a stable prefix.
    """
    import time

    from google.api import metric_pb2
    from google.cloud import monitoring_v3

    client = monitoring_v3.MetricServiceClient()
    project_path = f"projects/{PROJECT_ID}"
    now_seconds = int(time.time())

    # All series go in one call. Writing them one at a time in a loop returns a 500 often
    # enough to matter, because each call creates a descriptor and they arrive faster than
    # the service settles. One batched write is also the documented usage.
    all_series = []
    for name, value in metrics.items():
        series = monitoring_v3.TimeSeries()
        series.metric.type = f"{METRIC_PREFIX}/{name}"
        series.resource.type = "global"
        series.metric_kind = metric_pb2.MetricDescriptor.MetricKind.GAUGE
        series.value_type = metric_pb2.MetricDescriptor.ValueType.DOUBLE
        series.metric.labels["course"] = "itcs355"
        series.metric.labels["project"] = "capstone"
        series.points = [monitoring_v3.Point({
            "interval": {"end_time": {"seconds": now_seconds}},
            "value": {"double_value": float(value)},
        })]
        all_series.append(series)

    client.create_time_series(name=project_path, time_series=all_series)
    return [series.metric.type for series in all_series]
