# Deployment

The nightly job runs on Google Cloud, on a schedule, reporting to a dashboard, with an alert
that has fired on a real refusal.

## What is deployed

| Component | Detail |
|---|---|
| Container image | `itcs355-capstone@sha256:e55bc7bd…c166dd6`, built for `linux/amd64`, base pinned by digest, runs as a non-root user |
| Scheduled job | Cloud Scheduler `itcs355-capstone-nightly`, `0 2 * * *` Asia/Bangkok |
| Compute | Vertex AI custom job, `e2-standard-4`, **spot** |
| Identity | runs as `itcs355-train`, which can read and write storage and submit jobs, and nothing else |
| Input | `gs://itcs355-6688010/capstone/incoming/contacts.csv` |
| Output | `gs://itcs355-6688010/capstone/call-lists/call-list-YYYY-MM-DD.csv` |
| Metrics | six series under `custom.googleapis.com/itcs355/capstone/` |
| Dashboard | *ITCS355 capstone — nightly call list*, four panels |
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

## Cost

The schedule runs 30 times a month, about a minute each, on spot `e2-standard-4` at
3.860 THB/hour — roughly **1.93 THB per month**, matching the estimate in the cost report.
The dashboard, the alert and the six custom metric series are inside the free allowance.
