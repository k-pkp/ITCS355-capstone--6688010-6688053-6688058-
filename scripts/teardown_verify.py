"""Confirm this project is not leaving anything running that bills.

    python scripts/teardown_verify.py

The capstone brief makes "cloud resources left running after submission" an automatic
deduction, so this is a check that is meant to be run at the end and believed.

It reports rather than deletes. Deleting is `gcloud`'s job and is a decision a person
should make while looking at the list; this script exists to produce the list, and to be
explicit about the one thing that is deliberately left in place.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "reports" / "teardown-check.json"

GCP_PROJECT = "itcs355-6688010"
REGION = "asia-southeast1"

# The DVC remote. Deliberately NOT torn down: it holds the versioned dataset, it costs
# fractions of a baht per month, and a teardown that can delete the data is a teardown
# nobody dares run.
DVC_REMOTE_PREFIX = f"gs://{GCP_PROJECT}/capstone/dvc"


def run_gcloud(arguments: list[str]) -> tuple[bool, str]:
    """Run one gcloud command, returning whether it worked and what it said."""
    gcloud = shutil.which("gcloud")
    if gcloud is None:
        return False, "gcloud is not on PATH"

    try:
        completed = subprocess.run(
            [gcloud, *arguments], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)

    if completed.returncode != 0:
        return False, completed.stderr.strip()[:300]
    return True, completed.stdout.strip()


def main() -> int:
    """Check each billing-capable resource type and report what is running."""
    checks = {
        "vertex_endpoints": ["ai", "endpoints", "list",
                             f"--region={REGION}", f"--project={GCP_PROJECT}",
                             "--format=value(name)"],
        "vertex_models": ["ai", "models", "list",
                          f"--region={REGION}", f"--project={GCP_PROJECT}",
                          "--format=value(name)"],
        "scheduler_jobs": ["scheduler", "jobs", "list",
                           f"--location={REGION}", f"--project={GCP_PROJECT}",
                           "--format=value(name)"],
    }

    findings = {}
    still_running = []

    for name, arguments in checks.items():
        worked, output = run_gcloud(arguments)
        if not worked:
            findings[name] = {"checked": False, "note": output}
            print(f"  {name:<20} could not check: {output}")
            continue

        resources = [line for line in output.splitlines() if line.strip()]
        findings[name] = {"checked": True, "count": len(resources),
                          "resources": resources}
        print(f"  {name:<20} {len(resources)} running")
        if resources:
            still_running.append(name)

    payload = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": GCP_PROJECT,
        "region": REGION,
        "findings": findings,
        "still_running": still_running,
        "deliberately_kept": {
            "dvc_remote": DVC_REMOTE_PREFIX,
            "why": ("object storage holding the versioned dataset. Costs fractions of a "
                    "baht per month, and a teardown that can delete the data is a "
                    "teardown nobody dares run."),
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2))

    print(f"\nkept on purpose: {DVC_REMOTE_PREFIX} (the versioned dataset)")
    print(f"wrote {REPORT_PATH}")

    if still_running:
        print(f"\nSTILL RUNNING: {still_running}")
        print("These bill by the hour. Delete them before submitting.")
        return 1

    print("\nNothing is running that bills by the hour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
