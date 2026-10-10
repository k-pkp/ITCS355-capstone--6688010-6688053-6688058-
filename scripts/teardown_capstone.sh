#!/usr/bin/env bash
#
# Delete every capstone cloud resource that can bill, then verify nothing is left.
#
# The lab image repositories are deliberately not touched: the labs are graded as a
# separate submission and are not finished. scripts/teardown_verify.py knows which
# repositories those are and reports them separately rather than counting them as
# capstone resources left running.
#
# The versioned dataset in gs://itcs355-6688010/capstone/dvc is also kept. It costs
# fractions of a baht a month, and a teardown that can delete the data is a teardown
# nobody dares run.
#
#   scripts/teardown_capstone.sh --yes
#
# Nothing happens without --yes, because every command below is irreversible.

set -euo pipefail

PROJECT="itcs355-6688010"
REGION="asia-southeast1"
DASHBOARD_ID="44e3c10a-2dab-4849-8a5e-8bd03728712c"
ALERT_POLICY_ID="12323129586046041369"
CAPSTONE_IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/itcs355/itcs355-capstone"

if [[ "${1:-}" != "--yes" ]]; then
  echo "This deletes the capstone's schedulers, dashboard, alert policy and container"
  echo "image. It cannot be undone. Re-run with --yes to go ahead."
  exit 1
fi

echo "== scheduler jobs =="
for job in itcs355-capstone-feeder itcs355-capstone-nightly itcs355-capstone-measure; do
  gcloud scheduler jobs delete "${job}" \
    --location="${REGION}" --project="${PROJECT}" --quiet
done

echo "== dashboard =="
gcloud monitoring dashboards delete "${DASHBOARD_ID}" --project="${PROJECT}" --quiet

echo "== alert policy =="
# No GA gcloud command for alert policies, so this goes through the Monitoring API.
curl -fsS -X DELETE \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://monitoring.googleapis.com/v3/projects/${PROJECT}/alertPolicies/${ALERT_POLICY_ID}" \
  > /dev/null
echo "deleted alert policy ${ALERT_POLICY_ID}"

echo "== container image =="
gcloud artifacts docker images delete "${CAPSTONE_IMAGE}" --delete-tags --quiet

echo "== verifying =="
python scripts/teardown_verify.py
