# ITCS355 Capstone Proposal — nightly call-list ranker

**Pakkapol Boonluck (6688010) · Kritchanat Kulwanich (6688053) · Patcharapol Luksanakam (6688058)**

**1 · Problem and user.** A bank sells term deposits by telephone; 11.3% of calls succeed
and every failed call costs an agent's time. The service scores the contact list overnight
and publishes tomorrow's calls in ranked order. The user is the campaign supervisor who
exports that list each morning: they want an order, not a probability.

**2 · Dataset and licence.** UCI Bank Marketing, `bank-additional-full` — 41,188 rows, 20
columns, **CC BY 4.0** (Moro, Rita & Cortez 2014, DOI 10.24432/C5K306), versioned with DVC
and SHA-256 recorded. We take this variant rather than `bank-full.csv` because it carries
the macroeconomic columns recorded at call time, and the campaign ran May 2008 – November
2010 in time order, through the financial crisis: the subscription rate moves from 2.8% to
45.9% across the file. The monitoring half of the project therefore has a real distribution
shift to detect rather than an injected one.

The campaign is finished, so there is no live feed. It is **replayed**: a scheduled job
publishes the next slice of the held-out period each night and the scoring job treats it as
that day's export. The rows are real; only the calendar is synthetic. Because the outcomes
are already known, the published list can be scored against them the next morning — which a
live campaign cannot do until its labels arrive weeks later.

**3 · Latency and freshness.** Nobody waits on a prediction, so there is no latency
requirement worth defending. Input must be **under 24 hours old** when scored, the list must
be published well before the **08:00** export — the schedule runs 01:50 to 02:10 — and one
missed run is tolerable while two is an incident.

**4 · Serving pattern — scheduled nightly batch, not an endpoint.** 41,188 customers scored
once a day is 0.48 predictions per second, and nobody reads the result before 08:00 however
it is served. (That is the real campaign's rate; the replay is compressed to 600 customers a
night so that a fortnight of operation can be watched rather than waited for.) A managed endpoint bills 8.889 THB/hour whether or not anything calls it,
about **6,400 THB per month**, against roughly **7.70 THB** for the same work as scheduled
batch jobs on spot compute.

**5 · Planned failure mode — a stale input served as though it were current.** The overnight
export fails; yesterday's file is still in the bucket; the job reads it, scores it, and
publishes a list with a normal row count, a normal score distribution and no error anywhere.
In the morning, agents call the people they called yesterday. We chose this failure because
*nothing in an ordinary pipeline notices it* — every check that exists passes. The control
reads the input's own modification time before scoring and, when it is too old, **publishes
nothing and alerts**. A missing call list is fixed in ten minutes; a plausible wrong one is
worked through for a day.

**6 · Rough cost estimate.** About **7.70 THB per month**, at rates verified against the
Cloud Billing Catalog for `asia-southeast1`: three scheduled jobs at 1.93 each — feeding the
day's export, scoring it, and measuring yesterday's list against the outcomes — plus storage
and container registry ~1.90, with monitoring and scheduling inside the free allowance.
Retraining is run on demand and must pass the release gate; a retrain on a timer that cannot
be refused is a risk on a timer.

**7 · The work.** Six areas — data and reproducibility; modelling and evaluation; the
release gate and its lineage; operations, including the freshness gate and the failure
demonstration; monitoring and drift; documentation. Authorship and timestamps are recorded
in the repository's commit history.

Fuller detail — the leakage traps this dataset contains, the baselines the model must beat,
and the measured evidence for every figure above — is in [`README.md`](README.md) and
[`reports/`](reports/).
