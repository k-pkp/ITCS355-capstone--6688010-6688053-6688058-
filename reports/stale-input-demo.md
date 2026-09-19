# The stale input failure, and the gate that catches it

Both runs below scored **the same file**: a valid customer export of 3,000 rows, aged 26 hours. Nothing about its contents is wrong. Only its age is.

## Run 1 — without the freshness gate

- exit code **0**
- published: **True**
- rows published: **500**
- score range: 0.147 to 0.4474, median 0.2191
- errors: none

**The job succeeded.** It produced a call list of exactly the expected length, with a score distribution that looks like every other night's, and reported nothing wrong. A dashboard watching row counts, run duration, score ranges or exit codes sees a completely healthy run.

In the morning, agents call the people they called yesterday.

## Run 2 — with the freshness gate

- exit code **2**
- published: **False**
- refusal reason: **stale_input**
- input age: **26.0 hours**

Nothing was published. The refusal is recorded as a metric, so the alert fires on the absence of a list rather than on nobody noticing a wrong one.

## Why refusing beats guessing

The gate could have published yesterday's list with a warning attached. It does not, and that is the design decision worth defending: a missing call list is an obvious problem somebody fixes within minutes, while a plausible wrong one is worked through for a whole day and is discovered only when a customer complains about being called twice.

## What the gate actually checks

The input's own modification time, not the HTTP status of the read, not the row count, and not the job's own clock. Every one of those was fine in run 1.

The limit is 24 hours, from the freshness requirement in the proposal: the list is consumed once a day, so an input older than a day describes a day that has already been worked through.

## Guarded by

`tests/bank/test_freshness.py` — ten tests, including the boundary pinned from both sides, because a later change from `<=` to `<` would move it silently.
