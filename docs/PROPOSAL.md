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

## The work

| Area | What it covers |
|---|---|
| Data and reproducibility | Acquisition with licence and SHA-256 recorded, DVC versioning, the seven-rule data contract, the time-ordered split |
| Modelling and evaluation | Feature building with the leakage guards, training, the two baselines, lift at a call budget |
| Release control | The evaluation gate and the lineage it requires before a model may be registered |
| Operations | The nightly batch job, the freshness gate, and the failure demonstration |
| Monitoring | Drift scoring across seven columns, per-run metrics, the teardown check |
| Documentation | README, design, glossary, cost report, model card, this proposal |

Every change is recorded in the repository's commit history with its author and timestamp,
so the record of who did what is in the repository rather than in this table.
