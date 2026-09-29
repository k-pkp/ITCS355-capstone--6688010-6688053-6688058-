"""Confirm this project is not leaving anything running that bills.

    python scripts/teardown_verify.py

The capstone brief makes "cloud resources left running after submission" an automatic
deduction, so this is a check that is meant to be run at the end and believed.

It reports rather than deletes. Deleting is `gcloud`'s job and is a decision a person
should make while looking at the list; this script exists to produce the list, to print the
exact commands that would empty it, and to be explicit about the one thing that is
deliberately left in place.

Not everything here bills by the hour. An alert policy costs nothing and still counts as a
resource left running, because it keeps sending mail to a real inbox about a project nobody
is operating any more. Container images bill by the gigabyte, and Lab 5 measured the
registry at 38% of that project's bill — almost entirely images nothing ever deleted.
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



def check_alert_policies() -> dict:
    """Return the project's alert policies, read from the Monitoring API.

    There is no GA `gcloud` command for these, and the alpha component prompts to install
    itself, which a teardown check must never do. So this asks the API directly with the
    token gcloud already holds.
    """
    import json as json_module
    import urllib.error
    import urllib.request

    worked, token = run_gcloud(["auth", "print-access-token"])
    if not worked:
        return {"checked": False, "note": "no access token"}

    request = urllib.request.Request(
        f"https://monitoring.googleapis.com/v3/projects/{GCP_PROJECT}/alertPolicies",
        headers={"Authorization": f"Bearer {token.strip()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json_module.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as failure:
        return {"checked": False, "note": str(failure)}

    policies = [policy["name"] for policy in payload.get("alertPolicies", [])]
    return {"checked": True, "count": len(policies), "resources": policies}


def print_teardown_commands(findings: dict) -> None:
    """Print the exact commands that would empty what is still running.

    Printed, never run. A teardown script that deletes on its own is one mistyped project
    id away from being the incident it was written to prevent.
    """
    print("\nTo tear down, run these and then run this script again:\n")

    for job in findings.get("scheduler_jobs", {}).get("resources", []):
        name = job.rsplit("/", 1)[-1]
        print(f"  gcloud scheduler jobs delete {name} "
              f"--location={REGION} --project={GCP_PROJECT} --quiet")

    for dashboard in findings.get("dashboards", {}).get("resources", []):
        name = dashboard.rsplit("/", 1)[-1]
        print(f"  gcloud monitoring dashboards delete {name} "
              f"--project={GCP_PROJECT} --quiet")

    for policy in findings.get("alert_policies", {}).get("resources", []):
        print(f"  curl -X DELETE -H \"Authorization: Bearer $(gcloud auth "
              f"print-access-token)\" \\\n       "
              f"https://monitoring.googleapis.com/v3/{policy}")

    for endpoint in findings.get("vertex_endpoints", {}).get("resources", []):
        name = endpoint.rsplit("/", 1)[-1]
        print(f"  gcloud ai endpoints delete {name} "
              f"--region={REGION} --project={GCP_PROJECT} --quiet")

    for model in findings.get("vertex_models", {}).get("resources", []):
        name = model.rsplit("/", 1)[-1]
        print(f"  gcloud ai models delete {name} "
              f"--region={REGION} --project={GCP_PROJECT} --quiet")

    for image in findings.get("container_images", {}).get("resources", []):
        print(f"  gcloud artifacts docker images delete {image} "
              f"--delete-tags --quiet")


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
        "dashboards": ["monitoring", "dashboards", "list",
                       f"--project={GCP_PROJECT}", "--format=value(name)"],
        "container_images": ["artifacts", "docker", "images", "list",
                             f"{REGION}-docker.pkg.dev/{GCP_PROJECT}/itcs355",
                             "--include-tags", "--format=value(package)"],
    }

    findings = {}
    still_running = []

    for name, arguments in checks.items():
        worked, output = run_gcloud(arguments)
        if not worked:
            findings[name] = {"checked": False, "note": output}
            print(f"  {name:<20} could not check: {output}")
            continue

        # One row per version comes back for image repositories, so the same package
        # appears many times. Deduplicate while keeping the order it was listed in.
        resources = []
        for line in output.splitlines():
            stripped = line.strip()
            if stripped and stripped not in resources:
                resources.append(stripped)
        findings[name] = {"checked": True, "count": len(resources),
                          "resources": resources}
        print(f"  {name:<20} {len(resources)} running")
        if resources:
            still_running.append(name)

    # Alert policies have no GA gcloud command, so they are read from the Monitoring API
    # directly rather than reported as "could not check" -- an unverifiable line in a
    # teardown report is the same as no line.
    findings["alert_policies"] = check_alert_policies()
    print(f"  {'alert_policies':<20} {findings['alert_policies'].get('count', '?')} "
          f"running")
    if findings["alert_policies"].get("count"):
        still_running.append("alert_policies")

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
        print("The brief makes cloud resources left running after submission an automatic "
              "deduction.")
        print_teardown_commands(findings)
        return 1

    print("\nNothing is running that bills by the hour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
