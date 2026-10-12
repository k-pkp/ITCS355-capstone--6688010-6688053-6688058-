# Deployment

The nightly job runs on Google Cloud, on a schedule, reporting to a dashboard, with an alert
that has fired on a real refusal.

## What is deployed

| Component | Detail |
|---|---|
| Container image | `itcs355-capstone@sha256:e55bc7bd…c166dd6`, built for `linux/amd64`, base pinned by digest, runs as a non-root user |
| Scheduled jobs | `itcs355-capstone-feeder` at `50 1 * * *` publishes the next replayed day; `itcs355-capstone-nightly` at `0 2 * * *` scores it. Two jobs on purpose — see [`replay.md`](replay.md) |
| Compute | Vertex AI custom job, `e2-standard-4`, **spot** |
| Identity | runs as `itcs355-train`, which can read and write storage and submit jobs, and nothing else |
| Input | `gs://itcs355-6688010/capstone/incoming/contacts.csv`, rewritten nightly by the feeder from `capstone/replay/source.csv` |
| Output | `gs://itcs355-6688010/capstone/call-lists/call-list-YYYY-MM-DD.csv` |
| Metrics | six series under `custom.googleapis.com/itcs355/capstone/` |
| Dashboard | *ITCS355 capstone — nightly call list*, six panels. Four describe the run; two describe the **result** — the realised lift of the published list and the subscriptions it gained over calling the same people at random. A dashboard of inputs can say the job ran; only those two can say it helped. |
| Alert | *nightly run refused to publish*, on `published < 1` |

## The freshness gate reads the object's own timestamp

A detail worth stating, because the obvious implementation is wrong. Downloading the input
and checking the local file's modification time would always report the file as fresh — the
copy was written the moment it was downloaded, which is always now.

So the age comes from the **object's** metadata in the bucket, before the download is used
for anything. `src/bank/cloud.describe_object` returns it, and the job builds its freshness
decision from that rather than from the copy on disk.

## The alert, proved rather than configured

An export with an unknown job category was uploaded, and the job refused it:

```
CONTRACT VIOLATION — published nothing:
  unexpected_category: job contains ['influencer'], which is not in its vocabulary (200 rows)
```

The `published` metric over that period:

| Time (UTC) | published |
|---|--:|
| 01:21:18 | 1 |
| 01:22:06 | 1 |
| 01:31:50 | 1 |
| **01:34:29** | **0** |
| 01:35:18 | 0 |
| 01:36:33 | 0 |

The alert condition is `published < 1`, so the refusal is exactly what it watches. Good
input was then restored and the metric returned to 1.

**Why the alert watches "did not publish" rather than "job failed".** A job that crashes is
already visible. The failure this project is built around is a job that *succeeds* and
publishes the wrong list. The metric that separates those two is whether a list was
published at all, and the refusal paths are the only thing that can drive it to zero.

## The first scheduled run

The image was rebuilt after the model was retrained and registered, and the scheduled job
was repointed at the new digest. Forced to run, it produced:

| | |
|---|---|
| Vertex job `7218116540099461120` | SUCCEEDED |
| Published | `gs://itcs355-6688010/capstone/call-lists/call-list-2026-09-21.csv`, 500 rows |
| `published` metric | 1 at 01:58:45Z |
| Duration | 12.31 s |

The list it published is ranked by `bank-call-list-ranker` **version 2** — the version
`approved-model.json` approves, with its 13 lineage fields in
[`bank-registry.md`](bank-registry.md).

That run scored the whole 3,000-row export, hence 500 rows at a call share of 16.67%. The
replay was switched to 600-row nights shortly afterwards so that a fortnight of operation
could be watched instead of waited for, and the call budget scales with the export — see
[`replay.md`](replay.md). **The object named above now holds 100 rows**, because the
scheduled run that night overwrote it; call lists are named by date, and this forced run and
the first scheduled run fell on the same date.

## What the deployment then did, for twelve nights and then seven

The schedule ran unattended from 21 September. Thirty-six consecutive SUCCEEDED jobs — twelve
nights of feeder, scorer and measure — published twelve call lists at a mean realised lift of
1.279×. Then the held-out period ran out, and the scorer refused on staleness for seven
consecutive nights while an alert stayed open.

That is the most useful evidence this project has, because nobody arranged it. It is written
up with the Cloud Logging output and the metric series in
[`incident-2026-10-04.md`](incident-2026-10-04.md), including why Vertex reports the seven
refused nights as `JOB_STATE_FAILED` and why the metric rather than the job state is the
thing the alert watches.

## Three failures on the way to a working deployment

Each one was found by running it, and each would have been invisible from reading the code.

**1. The lock file did not contain the cloud libraries.** `requirements.in` pinned
`pandas==2.4.1` and `scikit-learn==1.8.2`, versions that were never released. The lock step
failed — and its output had been redirected to `/dev/null`, so the failure was silent and
the image was built from the previous lock. The container resolved the right cloud and then
died on `ModuleNotFoundError: No module named 'google.cloud'`.

*The lesson is not about pinning.* It is that a step which can fail was made unable to
report it.

**2. The lock was resolved for the wrong Python.** Recompiling produced `scipy==1.18.1`,
which requires Python 3.12, while the image is 3.11. Fixed by compiling with
`--python-version 3.11`, so the lock is resolved for the interpreter that will actually run.

**3. The container could not write its own working directory.** It runs as a non-root user,
by design, and `/app/data` is owned by root. The job now writes its working copy to `/tmp`
and publishes to the bucket, which is where the output belongs anyway.

## Torn down on 12 October

Everything above has been deleted. The course requires it, and leaving cloud resources
running is a marked deduction, so anyone opening the console after 12 October 06:31Z finds
nothing — no schedulers, no dashboard, no alert policy, no capstone image.

```
vertex_endpoints     0 running
vertex_models        0 running
scheduler_jobs       0 running
dashboards           0 running
container_images     0 running (5 kept for the labs)
alert_policies       0 running
```

`scripts/teardown_capstone.sh --yes` deleted them and then
[`teardown_verify.py`](../scripts/teardown_verify.py) re-queried each API and wrote
[`teardown-check.json`](teardown-check.json), whose `still_running` list is empty. The
verification is separate from the deletion on purpose: a teardown script that reports its own
success is a teardown script nobody can check.

Two things were kept deliberately, and the record says so rather than hiding them: the five
**lab** image repositories, because the labs are a separate submission that is not finished,
and `gs://itcs355-6688010/capstone/dvc`, the versioned dataset, at fractions of a baht a
month — a teardown that can delete the data is a teardown nobody dares run.

What survives the deletion is the evidence, not the infrastructure:
[`alert-policy.json`](alert-policy.json), [`monitoring-dashboard.json`](monitoring-dashboard.json),
the image digest in [`image-digest.txt`](image-digest.txt), and the logs and metric series
quoted in [`incident-2026-10-04.md`](incident-2026-10-04.md).

## Cost

The schedule runs 30 times a month, about a minute each, on spot `e2-standard-4` at
3.860 THB/hour — roughly **1.93 THB per month** for the scorer, **5.79** for all three
scheduled jobs, and **~7.70** once storage and the container registry are counted.
The dashboard, the alert and the six custom metric series are inside the free allowance.
