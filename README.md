# ITCS355 Capstone — call-list ranker

Ranks a bank's customer contact list so agents call the most promising people first,
published as a nightly batch to a schedule on Google Cloud. Built to demonstrate an
operational system, not a model.

**The model appeared to lose to a single column, and the interesting part is that the
measurement was wrong.** Sorting customers by the interbank rate — a number identical for
everyone contacted in the same week — beat the model when a whole year of calls was ranked
in one go. It cannot beat anything inside one night's export, which is the only thing the
job ever ranks. Fixing what was measured, and retraining on a recent window, changed the
gate's verdict from refuse to pass. Both runs are in the repository.

---

## The thing this project is actually about

An overnight customer export fails to arrive. Yesterday's file is still in the bucket. The
job reads it, scores it, and publishes a call list with the right number of rows, a normal
score distribution, and no error anywhere. The dashboard stays green.

In the morning, agents call the people they called yesterday.

Nothing in an ordinary pipeline notices, because nothing in an ordinary pipeline asks *when*
the data is from — it asks whether the read succeeded, and the read succeeded.

**The control is a freshness gate that publishes nothing rather than something plausible.**
A missing call list is an obvious problem somebody fixes in ten minutes. A wrong one is
worked through for a day.

Demonstrated, both ways, on the same file:

| | Without the gate | With the gate |
|---|---|---|
| Exit code | 0 | 2 |
| Published | **500 customers** | nothing |
| Score range | 0.147 – 0.447, median 0.219 | — |
| Errors | none | none |
| Age of input | 26 hours | 26 hours |

Full write-up: [`reports/stale-input-demo.md`](reports/stale-input-demo.md).
Reproduce it: `python scripts/demo_stale_input.py`.

---

The one-page proposal, as submitted at M2, is [`PROPOSAL.md`](PROPOSAL.md).

---

## Reproduce everything

```bash
pip install -r requirements.txt

python scripts/download_bank_data.py      # or: dvc pull
pytest -q                                 # 67 tests
python scripts/train_bank.py              # trains and scores against baselines
python scripts/register_bank_model.py     # asks the gate; currently passes
python scripts/check_drift.py             # 6 of 7 columns alerting
python scripts/demo_stale_input.py        # the failure, with and without the gate
```

Nothing above needs cloud credentials. `dvc pull` needs access to the GCS remote; the
download script is the alternative and produces a byte-identical file.

---

## Data

| | |
|---|---|
| Source | UCI Bank Marketing, `bank-additional-full` variant |
| Rows | 41,188 · 20 input columns |
| Period | May 2008 – November 2010, in stored order |
| Licence | **CC BY 4.0** — Moro, Rita & Cortez (2014), DOI 10.24432/C5K306 |
| Versioning | DVC; SHA-256 recorded in `data/bank/dataset.json` |

**Which variant matters.** The commonly used `bank-full.csv` has 45,211 rows and no
macroeconomic columns. This one carries the Euribor rate, employment variation and price
indices recorded at call time — and because the campaign ran in time order straight through
the financial crisis, those columns contain a real distribution shift rather than a
simulated one.

| | Start of campaign | End |
|---|--:|--:|
| Euribor 3-month | 4.86 | 0.80 |
| Subscription rate | 2.8% | 45.9% |

---

## The trap that looks fine

Splitting this dataset at random hides the entire shift:

| Split method | First half | Second half |
|---|--:|--:|
| Random 50/50 | 11.4% | 11.1% |
| **Time-ordered 50/50** | **4.7%** | **17.9%** |

The wrong method produces the reassuring number. So the prohibition is a test, not a
comment: `tests/bank/test_splits.py::test_the_time_split_exposes_the_distribution_shift`
asserts the *presence* of a difference, which is backwards on purpose — on this file,
halves that look alike mean somebody shuffled.

Two more guarded the same way:

- **`duration`** correlates 0.405 with the outcome and is the most predictive column. It
  records how long the call lasted, which is unknown when the list is built. Including it
  appears to lift 1.34× → 2.86× within month, all of it unavailable in
  production.
- **`pdays` uses 999** for "never previously contacted", in 96.3% of rows. Split into a flag
  and a day count before the model sees it.

---

## Results, and the measurement that was wrong

The first version of this project reported these numbers, and the gate refused the model:

| Ranking, whole test period at once | Subscriptions in top 500 | Lift |
|---|--:|--:|
| Call in file order | 32 | 0.21× |
| This model | 207 | 1.34× |
| **Sort by `euribor3m` alone** | **278** | **1.80×** |

```
GATE FAIL
  - lift 1.34 does not clear the best baseline (euribor3m, 1.80)
    by the required 0.05; it needs 1.85
```

**One column with no per-customer information was beating the model.** `euribor3m` is the
interbank rate — identical for everyone contacted in the same week. It cannot tell one
customer from another. That should stop work, not prompt a retrain.

It won because the measurement let it answer a different question. Ranking 8,239 rows that
span months by `-euribor3m` sorts them, near enough, **by date**, and the late months are
when people subscribed. The deployed job never gets that chance: it ranks one export, whose
customers were all contacted at about the same time.

Measured the way the job actually runs — inside one contact month:

| Ranking, within one month | Lift | Worst month |
|---|--:|--:|
| Call in file order | 0.81× | 0.64× |
| Sort by `euribor3m` alone | 0.96× | 0.41× |
| **This model** | **1.34×** | **1.25×** |
| With `duration` (leaky, never registered) | 2.86× | 1.33× |

The baseline at 0.96× is not a strong opponent narrowly beaten. It is **no better than
calling people in no particular order**, which is what a column that is constant inside a
batch should be.

A second, independent fix: the model now trains on the most recent 4,000 rows rather than
all 24,712, because the campaign spans a financial crisis and older rows describe a
different world. The window size was chosen on the validation period. That change alone
raises even the old whole-period score from 1.34× to 1.97×, which clears the old gate too
— the model was undertrained *and* the measurement was wrong.

```
candidate  within month: lift 1.34x across 13 months, worst month 1.25x
GATE PASS
```

Registered as `bank-call-list-ranker` version 1 with nine lineage fields:
[`reports/bank-registry.md`](reports/bank-registry.md). Full working, including a
hypothesis that was tested and turned out wrong:
[`reports/bank-export-evaluation.md`](reports/bank-export-evaluation.md).

**The measured limit.** On the validation period — the crisis onset — the same model scores
1.07× within month and falls below 1.0 in two of its four months. This model's skill does
not survive a regime break. That is why the drift monitor exists, and it is in the
[model card](reports/model-card.md) as a known limit rather than a footnote.

---

## Monitoring

`python scripts/check_drift.py` — 6 of 7 watched columns above the PSI threshold of 0.20.

**This run is expected to alert.** A drift check finding nothing here would mean the
detector was broken, not that the world was calm.

One limit carried over from Lab 4: **PSI measures how far the input moved, not how much the
model minds.** A shift scoring 0.383 cost 0.0100 ROC AUC there, while one scoring 0.2627
cost 0.0167. PSI opens an investigation; it does not rank incidents.

---

## Deployment

The nightly job runs on Google Cloud, on a schedule, and reports to a dashboard with an
alert that has already fired on a real refusal.

| | |
|---|---|
| Schedule | Cloud Scheduler `itcs355-capstone-nightly`, `0 2 * * *` Asia/Bangkok |
| Compute | Vertex AI custom job, `e2-standard-4`, spot |
| Image | `itcs355-capstone@sha256:e55bc7bd…c166dd6`, base pinned by digest, non-root |
| Identity | `itcs355-train` — read and write storage, submit jobs, nothing else |
| Output | `gs://itcs355-6688010/capstone/call-lists/call-list-YYYY-MM-DD.csv` |
| Alert | fires when `published < 1`, i.e. when a run **refused** rather than when it crashed |

The alert was proved rather than configured: an export carrying an unknown job category was
uploaded, the contract refused it, and the `published` series went 1 to 0. Working:
[`reports/deployment.md`](reports/deployment.md).

---

## "The data is not live. How does it run day by day?"

The campaign is **replayed**. A separate scheduled job publishes the next slice of the
held-out period every night at 01:50, and the scoring job treats it as today's export at
02:00. The rows are real; only the calendar is synthetic.

Two jobs rather than one, on purpose: **if the feeder fails, nothing rewrites the export, it
ages past 24 hours, and the scorer refuses.** The failure the project is built around then
happens for real instead of being simulated by editing a timestamp.

And the replay can do one thing a live system cannot. The campaign finished in 2010, so the
outcomes are already known, and last night's published list can be scored **the next
morning**:

```
export:  600 customers, 44 subscribed (7.3%)
called:  100 customers, 10 subscribed (10.0%)
realised lift: 1.36x  (+2.7 subscriptions against calling the same 100 at random)
```

A live campaign waits weeks for those labels — Lab 3 hit exactly that wall, which is why its
canary had to use a label-free proxy too weak to see anything. Full design, including why
the replay stops rather than looping: [`reports/replay.md`](reports/replay.md).

---

## Cost

| Serving pattern | THB / month |
|---|--:|
| Always-on managed endpoint | ~6,400 |
| **Nightly batch on spot (chosen)** | **1.93** |

An endpoint bills 8.889 THB/hour whether or not anything calls it, to serve 0.48 predictions
per second that nobody waits for. Full working: [`reports/cost-report.md`](reports/cost-report.md).

---

## Layout

```
src/bank/          contract, splits, features, evaluate, gate, freshness, monitoring,
                   cloud (object storage and metrics)
Dockerfile         the image the scheduled job runs, base pinned by digest
scripts/           download, train, register, score_nightly, check_drift,
                   feed_next_day and measure_yesterday (the replay), demos
tests/             59 tests
reports/           training, drift, gate decision, cost, model card, the demo
```

The reasoning behind each step — what it is, why it is needed, what breaks without it, and
how the choice was checked — is recorded in the project's commit messages, and the measured
evidence for every claim above is in `reports/`.

---

## Four bugs the guards caught, in the code that guards

Each of these was found by something in this repository rather than by review, and each was
silent:

1. **The drift detector reported a column that moved completely as perfectly stable.**
   `nr.employed` has three distinct values in the training window; quantile edges collapsed
   to two, both were overwritten with infinities, and every row landed in one bucket. PSI
   read 0.0000 for a column whose reference and current ranges do not even overlap. It now
   reads 9.89.
2. **The lineage field `data_version` came back empty**, because the DVC pointer writes
   `- md5:` under a YAML list item and the parser matched only `md5:`. The gate refused the
   registration and the bug was fixed instead of shipped.
3. **The model lost to a single column**, which nobody would have known without measuring a
   baseline first.
4. **An empty export crashed the nightly job**, reaching the model and raising a library
   error about array shapes — a stack trace saying nothing about the export having failed,
   arriving for whoever is on call. It is now a contract rule with a readable refusal.

---

## What is not done

- **The data is a fixed historical snapshot, and the system is not live.** This makes the
  pipeline strongly reproducible — one commit names one dataset by hash, and a fresh clone
  plus `dvc pull` returns it byte-identically. It also means two things worth saying plainly:
  the nightly job scores a slice of the same 2010 file rather than a genuinely new export,
  and the drift detected is a real shift that happened in 2008–2010 being **replayed**, not
  one observed as it happens. The shift is real data rather than injected noise, which is
  why this dataset was chosen; it is not live.
- **No billing export**, so the cost figures are rebuilt from Lab 5's measured rates
  and this project's own job durations rather than read off an invoice. The deployment
  itself is real; the accounting of it is measurement.
- **The registry is a local SQLite file**, not a hosted one, so "registered" means
  registered on this machine. Its contents are written out to
  [`reports/bank-registry.md`](reports/bank-registry.md) so the claim can be checked
  without it.
- **No group-fairness measurement.** Noted in the [model card](reports/model-card.md)
  rather than omitted.
