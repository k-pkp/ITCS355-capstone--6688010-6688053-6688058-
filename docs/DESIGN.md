# Design and methodology

PM2.5 six-hour nowcast — ITCS355 capstone.

This document exists so that every part of the system can be argued for out loud. For each
step it answers four questions: **what it is**, **why it is needed**, **what breaks without
it**, and **how we know the choice is right**. The last question is the one that carries
marks, because the brief grades the operational system and its defence, not the model.

---

## 1. The system in one flow

```
                     ┌──────────────── once, by hand ────────────────┐
                     │  pin stations + licences  →  download history  │
                     └───────────────────────┬───────────────────────┘
                                             │
                                    data contract (CI)
                                             │
                                     quality screen
                                             │
                                  features → train → registry
                                             │
   ┌─────────────────────── every hour, unattended ───────────────────────┐
   │  fetch latest → STALENESS GATE → features → score → publish forecast  │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
                      metrics → dashboard → alert
                                   │
                            drift detection
```

The capitalised box is the one the project is really about. Everything else is competent
plumbing; the gate is the part with an argument behind it.

---

## 2. Principles that govern every decision below

These are not slogans. Each one has already changed a decision in this project.

**P1 — Measure before choosing.**
A number nobody measured is an opinion wearing a number's clothes. The staleness threshold
was "3 hours" in the first draft because three sounded careful. Measuring the gap
distribution said 2 hours, and gave the false-alarm rate that justifies it.

**P2 — Wrong output is worse than no output.**
A system that refuses to answer creates a visible problem somebody fixes in ten minutes. A
system that answers wrongly creates an invisible problem that is acted on. Every gate in
this design chooses refusal.

**P3 — A test that has never failed is not known to work.**
Rules are proved by breaking the data on purpose and watching them fire. We also run a
mutation check: disable a rule, confirm the matching test goes red, restore it.

**P4 — One definition, used in both places.**
Anything enforced in CI and again at serving time is written once and imported twice. Two
copies always drift, and always in the direction of the serving copy being weaker than the
one people review.

**P5 — Accuracy earns nothing here.**
The brief says so explicitly. Effort goes to the operational system. The model is the
cheapest thing that beats persistence.

---

## 3. The steps

### Step 0 — Pin the stations, and record their licences

**What.** `scripts/find_stations.py` searches OpenAQ for Thai PM2.5 stations, keeps a fixed
list, and writes `data/stations.json` with each station's provider and licence beside it.

**Why it is needed.** "All Thai stations" is a different set of stations every month. A
dataset defined by a query cannot be rebuilt; a dataset defined by a list can.

**What breaks without it.** Retraining in November on "all Thai stations" silently trains on
a different population than the model in September. Every comparison between the two is
meaningless, and nothing in the system reports that anything changed.

**How we know it is right.** It is already load-bearing. The first run pinned 40 stations
that all turned out to state **no licence at all** — they were government Air4Thai monitors.
Checking all 618 Thai stations gave:

| Provider | Stations | Licence |
|---|--:|---|
| AirGradient | 346 | **CC BY 4.0** |
| Air4Thai | 263 | none stated |
| Clarity | 3 | CC0 1.0 |
| AirNow | 1 | US Public Domain |

The script now **refuses unstated licences by default**. Including them needs an explicit
flag, and then the proposal has to explain what it is relying on instead of a licence.

**Cost of the choice.** AirGradient are low-cost community sensors, not reference-grade
government instruments, so readings are noisier. Accuracy earns nothing (P5), and low-cost
sensors fail more often — which makes the failure demo more representative, not less.

---

### Step 1 — Download the history once, and version it

**What.** `scripts/download_measurements.py` pulls six months of hourly readings per station
into `data/raw/`, one CSV each. DVC tracks the directory; git tracks a 5-line pointer.

**Why it is needed.** Training must not depend on a live API. An API is slow, rate-limited,
needs a credential, and returns different data every hour.

**What breaks without it.** Training becomes irreproducible by construction — two runs an
hour apart see different data. The grader cannot rebuild your result, and neither can you.

**How we know it is right.** Verified, not assumed: cloned the repo into a fresh directory,
ran `dvc pull`, and confirmed all 39 files return **byte-identical** (md5 of the file set
matches). That round trip is what `dvc pull` claims and what nobody usually checks.

**Design detail that matters.** Missing hours are **skipped, never filled with zero**. A
zero would mean "the air was perfectly clean" instead of "we have no reading" — the exact
confusion the whole project is built around. Getting this wrong at download time would
quietly undermine the thing being graded.

---

### Step 2 — The data contract

**What.** `src/contract.py` holds rules as functions returning violations. Run in CI against
the dataset, and later in the hourly job against each batch.

**Why it is needed.** The upstream feed is not ours. It can rename a column, change units,
change aggregation, or start returning stations from another country. None of that raises an
error on its own.

**What breaks without it.** The quietest one is aggregation. If the endpoint stops landing on
the hour, every value stays plausible, nothing errors, and lag features silently begin
comparing readings a variable distance apart. No later test catches it, because the numbers
still look like PM2.5.

**How we know it is right.** Two layers:

1. `tests/test_contract_catches_breakage.py` breaks a clean frame in exactly one way per
   test and asserts the matching rule fires — dropped column, duplicated hour, null,
   negative, above ceiling, unaligned timestamp, unit change, wrong country, unpinned
   station, too little history, and several at once.
2. A **mutation check**: disabling the negative-concentration rule turns exactly two tests
   red; restoring it turns them green. A rule that can be disabled without any test noticing
   is not a rule.

**Design detail.** `validate()` returns *all* violations rather than raising on the first. A
feed that broke in three ways should take one afternoon to diagnose, not three builds.

**Deliberately not in the contract.** Exact zeros and absurd spikes. 25 of 39 stations report
at least one exact zero; one reports it 17.8% of the time. A real sensor network always
contains broken sensors, and a contract that fails on the normal state of the world gets
switched off. Those are handled in Step 3.

---

### Step 3 — Quality screen

**What.** `src/quality.py` screens each station and `scripts/screen_stations.py` writes
`data/excluded_stations.json` with the reason and the evidence for every exclusion.

**Why it is needed.** Contract failures mean *the feed broke*. Quality failures mean *this
sensor is bad*. They need different responses: stop everything, versus drop one station and
carry on.

**What breaks without it.** Training on station 2142493, which reports an impossible exact
zero 17.8% of the time, teaches the model that clean air is common at that location. Or the
opposite error: failing the whole build because one sensor is broken, which means nobody can
ship anything until a third party fixes hardware we do not own.

**How we know it is right.** Both thresholds sit inside a wide gap between the faulty
stations and the rest, so the answer does not depend on the exact number chosen.

*Zero rate, limit 5%.* The three worst stations are at 17.79%, 8.05% and 7.75%; the fourth
is at 1.48%. Any threshold between 1.5% and 7.7% selects the same three.

*Flat run, limit 24 hours.* Half of all stations never hold a value for more than 5 hours
and 95% stay under 15. The one faulty station ran 52; the next highest is 21.

The tests check both directions: each fault is caught, and a healthy station with a few
zeros or a few still hours is **not** excluded. A screen that excludes everything is as
useless as one that excludes nothing, and easier to write by accident.

**Result — 5 of 40 stations excluded, 35 usable:**

| Station | Reason | Evidence |
|---|---|---|
| 2142493 | implausible zero rate | exact zero in 17.8% of readings |
| 1236050 | implausible zero rate | 8.1% |
| 2165656 | implausible zero rate | 7.7% |
| 2457250 | **stuck sensor** | held one value for 52 consecutive hours |
| 2142801 | no readings | pinned but returned nothing |

**The exclusions live in a file, not in the training script.** A reviewer can see what was
dropped without reading code; the count becomes a monitored metric, so a fleet that is
quietly degrading is visible; and a station that recovers is readmitted by re-running the
screen rather than by someone remembering a hard-coded list exists.

---

### Step 4 — Features (not yet built)

**What.** Lagged PM2.5 (1, 2, 3, 6, 12, 24 hours), rolling means, hour of day, day of week,
station id.

**Why it is needed.** The model predicts the next six hours from the recent past. Those lags
*are* the signal.

**What breaks without it — and this is the trap.** Lags must be built **per station and in
time order**. Shift the whole frame and station A's history leaks into station B's features.
The model scores brilliantly in validation and fails in production, because it learned from
data it will never have at serving time.

**How we will know it is right.** Two defences. A test that builds features for two stations
with deliberately different values and asserts no value from one appears in the other. And
time-ordered splits — train on the earlier period, validate on the later one — never random
splits, which let the model see the future.

---

### Step 5 — Train, against a baseline that already exists

**What.** A gradient-boosted tree per horizon, or one model with horizon as a feature.

**Why the baseline first.** Persistence — "the value in six hours is the value now" — is
already measured:

| Horizon | Persistence mean absolute error |
|---|--:|
| +1h | 5.41 µg/m³ |
| +3h | 11.05 µg/m³ |
| +6h | 16.25 µg/m³ |

**What breaks without it.** A model with MAE 15.8 sounds like a result. It is 3% better than
doing nothing, which is not a result — it is a rounding error dressed as progress, and
nobody notices because there was nothing to compare against.

**How we know it is right.** The gate in Step 6 refuses to register a model that does not
beat persistence by a stated margin.

---

### Step 6 — Registry and lineage

**What.** The chosen model is registered with the fields that answer "where did this come
from": git commit, image digest, data version (the DVC hash), training job id, seed,
validation and test metrics.

**Why it is needed.** In three months, the only question that matters about a model in
production is which code and which data produced it.

**What breaks without it.** From Lab 2, measured: `git_commit` registered as the literal
string `unknown`, because the container has no `.git` directory. The field whose entire job
is to answer that question answered nothing — **and the registration still succeeded**. A
lineage field allowed to be empty without failing will be empty on the day it is needed.

**How we know it is right.** Registration fails when any lineage field is missing, rather
than warning.

---

### Step 7 — The hourly batch job

**What.** Cloud Scheduler triggers a container: fetch latest → gate → features → score →
publish → emit metrics.

**Why batch and not an endpoint.** A forecast that updates hourly cannot be more useful than
hourly, however it is served. Measured from Lab 3 and Lab 5 rates:

| Option | THB/month |
|---|--:|
| Always-on managed endpoint | ~6,400 |
| Every 30 min batch | 92.64 |
| **Hourly batch (chosen)** | **46.32** |
| Every 3 hours | 15.44 |
| Daily | 1.93 |

**Why not the cheapest row.** Three-hourly saves 31 THB a month and allows a forecast to be
two hours stale when someone reads it, which breaks the freshness requirement. Daily is
useless for a problem defined by intra-day change.

**The honest observation.** Cost here is dominated by the *number of runs*, not the work —
each run is about a minute. At 720 runs a month we are mostly paying per-job overhead. That
is the price of freshness, and it is invisible until you count the jobs.

---

### Step 8 — The staleness gate (the deliberate failure)

**The failure.** A station goes offline. The ingest returns 200 OK. The row count is
unchanged because the last known value is still there. The score distribution looks normal.
The model produces a confident forecast. The map shows clean air at a location with no data
at all — during exactly the episode when someone is checking whether it is safe to go
outside.

**Why this failure and not another.** It is invisible to every check a working pipeline
normally has. Nothing errors, nothing looks odd, and the output is acted on.

**The control.** Before scoring, read each measurement's **own timestamp** — not the HTTP
status. A station whose newest reading is older than **2 hours** is excluded and rendered as
"no data". The exclusion count is a monitored metric with an alert.

**Why 2 hours, with the number behind it.** Measured over six months:

- 99.5% of consecutive readings are exactly one hour apart
- gaps beyond 2 hours: 0.30% of intervals
- gaps beyond 3 hours: 0.23%

So 2 hours catches an outage an hour sooner, at a false-alarm cost of 0.07 percentage
points. A gate that fires during healthy operation gets switched off — and an ignored gate
is worse than no gate, because it also claims somebody is watching.

**We do not need to fake it.** Station 2457250 is real, and it failed in both ways.

### The gap this design originally had

Investigating that station changed the design. It did not merely spike — it sat at a median
of **1,680 µg/m³ for eight consecutive days** while every other station's p95 stayed under
60. That is a sensor stuck near its maximum, and the important part is this:

**A stuck sensor passes the staleness gate.** It reports fresh timestamps the whole time.
The data is current and completely wrong.

The original design checked whether data was *recent* and never whether it was *plausible*,
so this failure would have walked straight through it. The fleet has therefore two distinct
failures, needing two distinct controls:

| Failure | Looks like | Caught by |
|---|---|---|
| Station goes silent | no new readings | **staleness gate** — timestamp older than 2h |
| Station freezes | fresh readings, identical values | **flat-run check** — same value ≥ 24h |

Both controls belong in the hourly job, not only in the training screen, because both
failures happen live. The demo is stronger for it: we can show a station that disappears and
a station that lies, and show that only one of them is caught by the obvious defence.

Worth noting what did *not* catch the stuck sensor: the value 1,680 is under the contract's
physical ceiling of 2,000, so a range check passed it. It was only detectable by comparing
the station against itself over time, or against its neighbours.

---

### Step 9 — Monitoring, and drift that is real

**What.** Per-run metrics — rows in, stations excluded, forecast distribution, run duration —
plus PSI between a reference window and the current one.

**Why it is needed.** The label arrives six hours later, so quality cannot be checked at
serving time. Input-side statistics are the only same-day signal.

**What we get for free.** Burning season is a genuine distribution shift:

| Month | Median PM2.5 |
|---|--:|
| March | 76.1 |
| April | 72.0 |
| May | 12.5 |
| June | 5.6 |

March is 13× June. Most teams inject a synthetic shift; this one is in the data already, and
18.3% of all readings exceed Thailand's 24-hour standard of 37.5 µg/m³.

**What breaks without it.** From Lab 4, measured: PSI ranks by how far the input moved, not
by how much the model minds. A shift that scored 0.383 cost 0.0100 ROC AUC; one that scored
0.2627 cost 0.0167. The dashboard must therefore show both, or it ranks incidents wrongly.

---

### Step 10 — CI/CD

**What.** On every commit: lint → contract tests → breakage tests → feature leakage tests →
build image → integration test.

**Why it is needed.** The brief requires tests that can actually fail, and awards marks for
demonstrating one blocking a bad commit.

**What breaks without it.** From Lab 4, measured: dropping one column from the dataset export
looks like tidying. CI stopped it at the data contract step in 47 seconds, and the build job
was skipped, so no image was built and nothing was deployed.

---

### Step 11 — Cost accounting

**What.** A report with the estimate, the measured actual, the gap, and cost per 1,000
predictions.

**What breaks without it — measured in Lab 5.** Two corrections worth carrying into this
project:

- The endpoint was **46% of the entire bill for 1.45 hours of existence**.
- The container registry grew to 3.17 GB because nothing was ever deleted, becoming the
  second largest line. 0.9 GB of that arrived in one afternoon from pushing the same tag
  three times while debugging. **A debugging session is a storage cost.**

So this project gets a retention policy on untagged images from the start.

---

### Step 12 — Teardown

**What.** Delete every resource, then verify by listing and finding nothing.

**Why it is needed.** "Cloud resources left running after submission" is an automatic
deduction.

**What breaks without it — measured in Lab 5.** The teardown crashed partway through its list
with a 400 on a job that had already finished, leaving everything it had not yet reached
still billing, while its output read like a broken verifier rather than an accruing bill. A
cleanup routine that stops at the first surprise is worse than none, because it also reports
having tried.

---

## 4. Methodology: how decisions get made

**Decide with a measurement, then write the measurement next to the decision.**
Every threshold in this document is followed by the number that produced it. "2 hours,
because 0.30% of healthy intervals exceed it" survives a question. "3 hours, because that
seems safe" does not.

**Write the test before the thing it tests, where the test is the specification.**
The contract was written before the features that depend on it. It then found that our own
first station list had no licence — before a single feature existed.

**Break it on purpose, and keep the breakage.**
Every rule has a test that feeds it the exact failure it exists to catch. Those tests stay in
the suite permanently, so a future weakening turns something red.

**Prefer refusal to a plausible answer.**
Applied at the licence check (refuse unstated), the staleness gate (refuse stale), the
evaluation gate (refuse a model that ties persistence), and the registry (refuse incomplete
lineage).

**Carry the lab findings forward instead of rediscovering them.**
Six of the twelve steps above cite something measured in Labs 1–5. Those are not decoration:
they are the reason this design differs from the obvious one.

---

## 5. How the steps map to the marks

| Rubric | Worth | Steps |
|---|--:|---|
| R1 Reproducible pipeline | 6 | 0, 1, 2, 4, 5, 6 |
| R2 Deployment and CI/CD | 6 | 7, 10 |
| R3 Monitoring and reliability | 6 | 9, 12 |
| R4 Failure handling and defence | 6 | 3, 8 |
| R5 Documentation and presentation | 6 | 11, this document, model card, README |
| Live demo and defence | 15 | Step 8 is the demo |

---

## 6. Status

| Step | State |
|---|---|
| 0 Data acquisition | **done** — 41,188 rows, CC BY 4.0, SHA-256 recorded |
| 1 Versioning | **done** — DVC, pushed to GCS |
| 2 Data contract | **done** — 7 rules, mutation-checked |
| 3 Quality screen | not needed for a curated dataset; the air quality version stands as the worked example |
| 4 Features | **done** — `duration` excluded, `pdays` sentinel split, vocabulary-driven columns |
| 5 Train against baselines | **done** — the model loses, 1.34x against 1.80x |
| 6 Registry and lineage gate | **done** — refuses the current model, margin measured from seed noise |
| 7 Nightly batch job | **done** |
| 8 The deliberate failure | **done** — demonstrated both ways on the same file |
| 9 Monitoring and drift | **done** — 6 of 7 columns alerting; found a bug in the detector |
| 10 CI/CD | **done** — lint, tests, leakage guard called out |
| 11 Cost accounting | **done** — 1,400x between an endpoint and a nightly batch |
| 12 Teardown | **done** — nothing billing; the DVC remote kept on purpose |

**Note on the topic.** This design was written for the air quality nowcast and the project
moved to the bank dataset. The step structure, the principles and every lab finding cited
carry over unchanged, which is itself the useful observation: the design was about the
operational system, not about the data. Where the bank project differs —
`duration` instead of cross-station lags, a staged stale file instead of a dropped sensor —
the differences are written up in [`DESIGN-BANK.md`](DESIGN-BANK.md), and the parts of this
document that describe air quality specifics now describe the alternative rather than the
main line.

## 7. Open questions

1. ~~Station 2142801~~ — **decided**: left pinned, excluded by the quality screen with the
   reason recorded. It stays in the licence record and is accounted for, rather than
   vanishing from the station count.
2. **Forecast horizon.** Six hours is chosen because it is long enough to change an afternoon
   plan. It has not been tested against how far ahead the signal actually persists.
3. **Approval.** The proposal has not been approved yet. Steps 0–2 would transfer unchanged
   to the fallback topic; from Step 7 onward, the work is specific to this one.
