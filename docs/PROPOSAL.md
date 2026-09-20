# ITCS355 Capstone — Proposal

**Team:** Pakkapol Boonluck (6688010) · Kritchanat Kulwanich (6688053) · Patcharapol Luksanakam (6688058)  ·  **Submitted:** end of Session 3

## Problem, and who would use it

A bank sells term deposits by telephone. Most calls fail: in the campaign this dataset
records, **11.3% of calls ended in a subscription**. Every unsuccessful call costs an
agent's time.

The service scores the contact list overnight and publishes tomorrow's call list **in
order**, most likely to subscribe at the top. Agents work down from the top instead of
straight through.

The user is the campaign supervisor who exports that list each morning. They do not want a
probability per customer. They want an order, and they want to know when the order cannot be
trusted.

## Dataset and licence

**UCI Bank Marketing**, the `bank-additional-full` variant: **41,188 rows, 20 input
columns**, one binary outcome. Licensed **CC BY 4.0**; cited as Moro, Rita and Cortez
(2014), UCI Machine Learning Repository, DOI 10.24432/C5K306.

The archive contains four CSVs and **which one you take matters**. The commonly used
`bank-full.csv` has 45,211 rows and 16 inputs. We use the 41,188-row variant because it
carries five macroeconomic columns recorded at the time of each call — Euribor 3-month rate,
employment variation, consumer price and confidence indices, number employed — and those
columns are what make the monitoring half of this project real rather than simulated.

`scripts/download_bank_data.py` fetches it, records the SHA-256, and stores the licence and
citation alongside the data. DVC tracks the file, so a commit names exactly one dataset.

## The dataset contains a real distribution shift

The campaign ran **May 2008 to November 2010**, in time order, straight through the
financial crisis. Measured across the file:

| | Start of campaign | End of campaign |
|---|--:|--:|
| Euribor 3-month rate | 4.86 | 0.80 |
| Employment variation rate | +1.1 | −2.9 |
| Subscription rate | 2.8% | 45.9% |

**This is why the project is worth doing.** Most tabular datasets are a frozen snapshot with
no drift, so a monitoring story has to be invented. Here it is in the data, caused by a real
event, and the drift detection has something genuine to detect.

## Latency and freshness

Nothing waits on a prediction. The list is consumed once a day, in the morning. Every
requirement is about freshness, which is a different question and the one that governs the
design.

| Requirement | Target | Why |
|---|---|---|
| Input age at scoring time | ≤ 24 hours | The list is used daily; a two-day-old list ranks customers already called |
| Batch completed by | 06:00 | Supervisors export at 08:00, leaving two hours to retry |
| Availability | one missed run tolerated, two is an incident | A stale list is usable for a day and dangerous for two |

## Serving pattern, and why

**Scheduled batch, nightly.** Not an endpoint.

41,188 customers scored once a day is 0.48 predictions per second averaged out. Our Lab 5
measurements put a managed endpoint at **8.889 THB per hour whether or not anything calls
it** — about 6,400 THB a month to answer half a request a second that nobody is waiting for.
The same work as a nightly batch job on spot compute costs **1.93 THB a month**, a factor of
roughly 3,300.

Choosing online here would also buy nothing that could be used: agents read the list at
08:00 whether it was computed at 02:00 or at 07:59.

## The deliberate failure we are designing for

**A stale input feed, served as though it were current.**

The overnight customer export fails or arrives late. Yesterday's file is still in the
bucket. The job reads it, scores it, and publishes a call list that looks entirely normal —
same row count, same score distribution, no error anywhere, dashboard green. In the morning,
agents call the same people they called yesterday.

We chose this failure because **nothing in a normal pipeline notices it.** The job succeeds.
The model is fine. Every check that exists passes. The output is wrong and is acted on.

**The control:** read the input's own modification time before scoring, not merely whether
the read succeeded. If the file is older than the freshness requirement, **publish no list
at all** and raise an alert. A missing call list is an obvious problem somebody fixes in ten
minutes; a plausible wrong one is worked through for a day.

We will demonstrate it live: run the job against a deliberately stale file, show the list it
produces without the gate, then show the gate refusing and alerting, then show the test we
added so it cannot regress.

## A second failure the data creates by itself

Splitting this dataset at random rather than by time hides the entire distribution shift:

| Split method | First half subscribe rate | Second half |
|---|--:|--:|
| Random 50/50 | 11.4% | 11.1% |
| **Time-ordered 50/50** | **4.7%** | **17.9%** |

A random split reports two nearly identical halves and a model that validates beautifully.
The same model meets a period where the subscription rate is 3.8× different. **The wrong
method is the one that looks fine**, which is the property that makes it worth a test rather
than a comment.

Two further traps we will guard with tests rather than discipline:

- **`duration`** — how long the call lasted — correlates 0.405 with the outcome and is the
  single most predictive column. It is unusable: the call has not happened when the
  prediction is made. A test asserts it is absent from the feature list.
- **`pdays` uses 999** to mean "never previously contacted", in **96.3%** of rows. Treated as
  a number, the model learns something absurd about almost the entire dataset, and nothing
  errors.

## Rough cost estimate

Rates verified against the Cloud Billing Catalog for `asia-southeast1` during Lab 5.

| Line | Basis | THB / month |
|---|---|--:|
| Nightly scoring batch | 30 runs × ~60 s on spot `e2-standard-4` at 3.860 THB/h | 1.93 |
| Weekly retraining | 4 runs × ~3 min on spot | 0.77 |
| Object storage | dataset, DVC remote, published call lists | ~0.20 |
| Container registry | one image, retention policy on untagged versions | ~1.70 |
| Monitoring, alerting, scheduler | custom metrics, one policy, one schedule | 0.00 |
| **Total** | | **~4.6** |

**Cost per 1,000 predictions:** 41,188 scored per run at 0.064 THB — **0.0016 THB per
1,000**. The interesting figure is not this one. It is that an always-on endpoint would cost
about 6,400 THB a month to serve the same workload, and the entire value of the design
decision is in not doing that.

The registry carries a retention policy deliberately. In Lab 5 ours reached 3.17 GB and
became the second largest cost in the project, entirely from rebuilds nobody cleaned up.

## How we will know the model is worth deploying

Accuracy is the wrong measure here and we will not report it as a headline: the base rate is
11.3%, so a model that predicts "no" for everybody is **88.7% accurate and useless**.

The measure is lift at the top of the ranked list — *of the first 500 customers we call, how
many subscribe* — against two baselines that already exist: calling in file order, and
ranking by a single column. An evaluation gate refuses to register a model that does not
beat them by more than seed noise.

## What we are deliberately not doing

No deep learning, no feature store, no real-time serving. Model accuracy carries no marks,
so the model is a gradient-boosted tree and we stop tuning it the moment it beats the
baselines by more than seed noise.

We are also not building a user interface. The deliverable is a published call list and the
operational system around it; a front end would consume the time the failure demonstration
needs.

## What we considered instead

A six-hour PM2.5 nowcast over Thai air quality stations. We took it far enough to download
and version 155,109 hourly readings, profile them, and build a station quality screen, which
found five faulty sensors including one that reported a constant 1,680 µg/m³ for eight days
while still producing fresh timestamps.

We moved to this problem because it reaches an operationally complete system sooner while
keeping a real distribution shift and a real leakage trap. The air quality work remains in
the repository history, and the alternative design is written up alongside this one.
