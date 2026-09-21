"""Write out what the model registry actually holds.

    python scripts/describe_registry.py

The registry lives in a local SQLite file, which is not something a reviewer can open from
the repository. This writes its contents to reports/bank-registry.md so that "the model is
registered with lineage" is a claim anyone can check rather than one they have to believe.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.register_bank_model import MLFLOW_TRACKING_URI, MODEL_NAME

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"


def main() -> int:
    """Read every registered version and write its lineage to a report."""
    import mlflow

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.MlflowClient()

    versions = client.search_model_versions(f"name = '{MODEL_NAME}'")
    if not versions:
        print(f"no versions registered under {MODEL_NAME}")
        return 1

    lines = [
        f"# Model registry — `{MODEL_NAME}`",
        "",
        "Written by `scripts/describe_registry.py` from the registry itself, so that the "
        "claim can be checked rather than taken on trust.",
        "",
    ]

    for version in sorted(versions, key=lambda item: int(item.version)):
        lines += [
            f"## Version {version.version}",
            "",
            "| Lineage field | Value |",
            "|---|---|",
        ]
        for key in sorted(version.tags):
            lines.append(f"| `{key}` | `{version.tags[key]}` |")
        lines.append("")

    lines += [
        "## What each field is for",
        "",
        "| Field | Answers |",
        "|---|---|",
        "| `git_commit` | which code produced this |",
        "| `data_sha256` | whether a file is byte-identical to the one trained on |",
        "| `data_version` | which versioned copy to `dvc pull` to get those bytes back |",
        "| `seed` | what to set to reproduce the fit |",
        "| `feature_names_hash` | whether the serving code builds the same columns |",
        "| `train_rows` | how much history the model saw |",
        "| `metric_lift` / `metric` | what it scored, and on which measurement |",
        "| `worst_month_lift` | what it scored on its weakest month |",
        "| `trained_at_utc` | when |",
        "",
        "The gate refuses any registration where one of these is missing or reads "
        "`unknown`, which is what Lab 2 shipped without noticing.",
        "",
    ]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORTS_DIR / "bank-registry.md"
    output_path.write_text("\n".join(lines))
    print(f"wrote {output_path} — {len(versions)} version(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
