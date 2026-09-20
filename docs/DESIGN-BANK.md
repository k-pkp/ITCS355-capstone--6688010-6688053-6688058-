# Design and methodology — the alternative

Term deposit call list — ITCS355 capstone, **option B**.

This is the design for the fallback topic, written to the same depth as
[`DESIGN.md`](DESIGN.md) so the two can be compared fairly.

> **One asymmetry to hold in mind while reading.** Every number in the air quality design is
> measured — the data is downloaded, profiled, and five faulty stations were found by running
> the code. Every number here is *expected*. Nothing has been downloaded, nothing profiled,
> nothing found. That difference is not a point in either project's favour by itself, but it
> is the honest starting position of each.


> ### Correction, added after the data was downloaded
>
> **This document was written before the dataset was opened, and one of its central claims
> turned out to be wrong.** It says below that the bank project has no real drift and that
> everything interesting must be injected by hand. That is true of `bank-full.csv`. It is
> false of `bank-additional-full.csv`, which the project actually uses.
>
> The variant we use carries five macroeconomic columns recorded at call time, and the
> campaign ran May 2008 to November 2010 in stored order — through the financial crisis.
> Euribor falls from 4.86 to 0.80; the subscription rate rises from 2.8% to 45.9%; six of
> seven monitored columns cross the PSI alert threshold. **The drift is real and needs no
> injection.**
>
> The dataset also contains a genuine temporal leakage trap: a random 50/50 split reports
> 11.4% against 11.1% and hides the shift entirely, while a time-ordered split reports 4.7%
> against 17.9%.
>
> The paragraphs below are left as written, because the comparison is what the decision was
> made on and rewriting it would hide that the decision was made on partly wrong
> information. Read them knowing this correction exists.

---

## 1. The system in one flow

```
                     ┌──────────────── once, by hand ────────────────┐
                     │   download one CSV  →  check it  →  version it │
                     └───────────────────────┬───────────────────────┘
                                             │
                                    data contract (CI)
                                             │
                                  features → train → registry
                                             │
   ┌────────────────────── every night, unattended ───────────────────────┐
   │  read today's list → FRESHNESS GATE → score → rank → publish list     │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
                      metrics → dashboard → alert
                                   │
                            drift detection
```

---

## 2. What the system does

A bank sells term deposits by telephone. Most calls fail, and each one costs an agent's
time. Every night the system reads tomorrow's contact list, scores each customer, and
publishes the list **in order** — most likely to say yes at the top. Agents work down from
the top instead of through the whole thing.

The bank does not want a probability. It wants an order.

---

## 3. The steps

### Step 0 — Get the data

**What.** Download the UCI Bank Marketing dataset: one CSV, 45,211 rows, 16 input columns,
one yes/no outcome. Licence CC BY 4.0.

**Why it is easy.** It is a file. It does not change, there is no API, no key, no rate
limit, no pagination, no provider whose terms differ from the next provider's.

**What breaks without care.** Very little. This is the step where this option is
unambiguously cheaper — roughly five minutes against a full evening.

**The honest cost of that.** The dataset is a fixed historical snapshot from a Portuguese
bank. It will never change, which means **the project has no natural drift, no natural
outage, and no natural bad sensor.** Everything interesting has to be injected by hand.
More on that at Step 8.

---

### Step 1 — Version it

**What.** DVC tracks the CSV; git tracks the pointer.

**Why it is needed.** Identical reasoning to the other design: a commit must name exactly
one dataset.

**What breaks without it.** Less than in the air quality project, honestly. A static file
that never changes is much harder to accidentally retrain on a different version of. The
step is still required for R1, and it is still correct practice, but it defends against a
risk this project barely has.

---

### Step 2 — The data contract

**What.** Rules as importable functions, run in CI and again on each nightly batch:
required columns, no duplicate customer ids, age within a plausible human range, categorical
values drawn from the known set, `y` only ever `yes` or `no`.

**Why it is needed.** The file will not change — but the *feed* in the real system it
pretends to be would. The contract is what makes the exercise realistic, and it is what
catches the injected failure at Step 8.

**What breaks without it.** The strongest rule here is the categorical one. If an upstream
export starts writing `unknown` into the `job` column for 30% of rows, every value is still
a valid string, nothing errors, and the model quietly scores a third of the customer base
from a category it never learned. This is the bank equivalent of the unaligned-timestamp
failure, and it is just as quiet.

**How we know it is right.** Same two layers as the other design: break a clean frame one
way per test and assert the matching rule fires, then mutation-check that disabling a rule
turns exactly the expected tests red.

---

### Step 3 — Quality screen

**What.** Mostly not needed.

**Why.** There are no sensors, no stations, no devices to go faulty. A curated research
dataset has already had its quality problems removed by whoever curated it.

**What this costs the project.** In the air quality design, Step 3 is where the system found
a real stuck sensor and, through it, a genuine hole in the design. Here there is nothing to
find. That is less work, and also less to talk about in a defence.

---

### Step 4 — Features

**What.** Age, job, marital status, education, balance, housing and personal loans, contact
method, campaign history, days since previous contact, previous outcome.

**Why it is needed.** They are the signal.

**What breaks without care — and this project has its own trap.** The dataset contains
`duration`: how long the call lasted. It is the single most predictive column, and it is
**unusable**, because the call has not happened yet when the prediction is made. A model
trained with it scores beautifully and is worthless in production.

This is a leakage trap exactly as real as the cross-station lag trap in the other design,
and it has one advantage as a teaching example: it is famous. The dataset's own
documentation warns about it, which means a grader may well ask whether you noticed.

**How we know it is right.** A test asserting `duration` is absent from the feature list,
with a comment explaining why. That test is cheap and it is the single most valuable test in
this option.

---

### Step 5 — Train, against a baseline

**What.** A gradient-boosted tree producing a score per customer.

**The baseline.** Two of them, because ranking has two obvious dumb methods: call everyone in
file order, and call everyone sorted by a single column such as previous outcome.

**What breaks without it.** The class balance here is roughly 88% no. A model predicting
"no" for everybody is 88% accurate and completely useless. Any accuracy figure quoted
without that context is misleading, which is why the metric should be lift at the top of the
ranked list — *of the first 500 people we call, how many say yes* — not accuracy.

**Unmeasured.** Unlike the air quality baselines, which are computed, these numbers do not
exist yet.

---

### Step 6 — Registry and lineage

Identical to the other design, and identical in value: git commit, image digest, data
version, job id, seed, metrics. The `git_commit: unknown` failure from Lab 2 applies here
in exactly the same way.

---

### Step 7 — The nightly batch job

**What.** Cloud Scheduler triggers a container once a night: read list → gate → score →
rank → publish → emit metrics.

**Why batch.** For the same reason as the other project, only more so. Agents read the list
in the morning; nothing waits on a prediction at any point.

**Cost.** This is where option B wins clearly. Using the rates measured in Lab 5:

| | Air quality (hourly) | Bank (nightly) |
|---|--:|--:|
| Runs per month | 720 | 30 |
| Billed compute | 12.0 h | 0.5 h |
| **THB per month** | **46.32** | **1.93** |

Both are trivial against an always-on endpoint at ~6,400 THB/month. The interesting
difference is not the money, it is that the air quality cost story has something to argue
about — freshness bought at a price — and this one does not.

---

### Step 8 — The deliberate failure

**The failure.** The nightly customer export does not arrive. Yesterday's file is still in
the bucket. The job reads it, scores it, and publishes a call list that looks entirely
normal: same row count, same score distribution, no error anywhere, dashboard green. In the
morning, agents call the same people they called yesterday.

**Why it is a good failure.** It has the same shape as the air quality one, and it is the
shape that matters: *the job succeeds and the output is wrong.* Nothing in a normal pipeline
notices.

**The control.** Read the file's own modification time before scoring, not just whether the
read succeeded. If the file is older than the freshness SLO, **publish nothing and alert**.
A missing call list is a problem someone fixes in ten minutes; a plausible wrong one is
acted on for a day.

**The honest weakness, stated plainly.** This failure has to be **staged**. Nothing in the
data will ever produce it, because the CSV is a frozen snapshot from years ago. You will
demonstrate it by deliberately not copying a file.

Compare with the air quality project, where station 2457250 sat at 1,680 µg/m³ for eight
days on its own, and station 2142801 stopped reporting entirely, without anyone arranging
it. The difference between "here is a failure I arranged" and "here is a failure I found" is
the difference that a defence is graded on.

**A second, more interesting option for this project.** The dataset has a known
characteristic worth exploiting: `pdays` is −1 for customers never previously contacted, a
sentinel value masquerading as a number. A model treating −1 as "contacted −1 days ago"
learns something absurd, and nothing errors. This is a genuine, dataset-native trap — but it
is a *modelling* bug rather than an *operational* failure, and the brief grades operations.

---

### Step 9 — Monitoring and drift

**What.** Rows in, rows scored, rows rejected, score distribution, run duration, and PSI
against a reference window.

**The problem.** There is no real drift. The dataset is one frozen snapshot, so the
distribution never moves unless you move it.

**What you would do instead.** Split the file by campaign order, treat the earlier part as
the reference, and inject a shift — for example, re-weight the `job` distribution to
simulate the bank targeting a different customer segment. It works, it is defensible, and it
is visibly synthetic.

Compare: the air quality project's March median is 76.1 and its June median is 5.6, with no
intervention at all.

---

### Step 10 — CI/CD

Identical in both designs, and identical in value. Lint, contract tests, breakage tests,
leakage test, build, integration test. The blocked-bad-commit demo works the same way.

---

### Step 11 — Cost accounting

Same method, smaller numbers. The Lab 5 lessons apply unchanged: budget the thing that bills
by the hour, put a retention policy on untagged images from day one.

---

### Step 12 — Teardown

Identical.

---

## 4. The comparison, in the terms that decide it

| | Air quality | Bank |
|---|---|---|
| Data acquisition | one evening, API, key, pagination | 5 minutes, one file |
| **Already done** | **Steps 0–3 complete** | nothing started |
| Data volume | 155,109 rows, 35 usable stations | 45,211 rows |
| Real drift | yes — burning season, 13× | no — must be injected |
| Real broken data | yes — 5 stations, found by the code | no — dataset is curated |
| Deliberate failure | found in the data | staged by hand |
| Leakage trap | cross-station lags | `duration` column, well known |
| Running cost | ~46 THB/month | ~2 THB/month |
| External dependency | OpenAQ API, could break | none |
| Ongoing work | live feed must keep working | none |
| Risk of getting stuck | low, but real | very low |
| Defence material | strong | adequate |

### What switching would cost

Steps 0–3 are done for air quality: 155,109 rows downloaded and versioned, a profile, a
contract with 23 passing tests, a quality screen that found five faulty stations, and a
design change that came out of investigating one of them.

For the bank project, Steps 0 and 1 would take under an hour. Step 2 would take longer than
it sounds, because the rules are different, though the structure carries over. Step 3 mostly
disappears.

**Roughly: switching costs two or three hours and loses one genuinely interesting finding.**
The tests, the contract structure, the DVC setup, the CI, the cost method and the whole shape
of the design transfer unchanged.

### The question worth actually asking

Not "which is easier" — both are manageable. The question is which one you can still argue
for at the end of an eight-minute presentation when the instructor asks something you did
not prepare for.

With the air quality project the honest answer to most such questions is a number you
measured. With the bank project the honest answer is more often "we simulated that".

Against which: **finishing** matters more than impressing. A complete, boring project scores
every rubric row. An ambitious incomplete one scores none of them twice. Time available is
the constraint that should decide this, not which design reads better on paper.
