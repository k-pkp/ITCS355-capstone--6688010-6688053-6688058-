# ITCS355 Capstone — call-list ranker

Ranks a bank's customer contact list so agents call the most promising people first,
published as a nightly batch. Built to demonstrate an operational system, not a model:
**model accuracy carries no marks here, and this model currently loses to a single column.**
That is recorded rather than hidden, and the evaluation gate refuses to register it.

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

## Reproduce everything

```bash
pip install -r requirements.txt

python scripts/download_bank_data.py      # or: dvc pull
pytest -q                                 # 80 tests
python scripts/train_bank.py              # trains and scores against baselines
python scripts/register_bank_model.py     # asks the gate; currently refused
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
  appears to lift 1.34× → 2.17×, all of it unavailable in production.
- **`pdays` uses 999** for "never previously contacted", in 96.3% of rows. Split into a flag
  and a day count before the model sees it.

---

## Results, as measured

| Ranking | Subscriptions in top 500 | Lift |
|---|--:|--:|
| Call in file order | 32 | 0.21× |
| This model | 207 | 1.34× |
| **Sort by `euribor3m` alone** | **278** | **1.80×** |
| With `duration` (leaky, never registered) | 335 | 2.17× |

**The model loses.** The evaluation gate refuses it:

```
GATE FAIL
  - lift 1.34 does not clear the best baseline (euribor3m, 1.80)
    by the required 0.05; it needs 1.85
```

The margin is measured, not chosen: five seeds give 1.3105–1.3494 lift, sd 0.0152, so 0.05
sits above two standard deviations. A model clearing it has improved rather than drawn a
luckier seed.

The cause is the shift. The model learned a 4.8% world and met a 30.8% one, while
`euribor3m` works as a clock — low rate means late campaign means easy subscriptions.

---

## Monitoring

`python scripts/check_drift.py` — 6 of 7 watched columns above the PSI threshold of 0.20.

**This run is expected to alert.** A drift check finding nothing here would mean the
detector was broken, not that the world was calm.

One limit carried over from Lab 4: **PSI measures how far the input moved, not how much the
model minds.** A shift scoring 0.383 cost 0.0100 ROC AUC there, while one scoring 0.2627
cost 0.0167. PSI opens an investigation; it does not rank incidents.

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
src/bank/          contract, splits, features, evaluate, gate, freshness, monitoring
src/airquality/    the alternative topic that was evaluated first
scripts/           download, train, register, score_nightly, check_drift, demos
tests/bank/        57 tests   tests/airquality/  23 tests
docs/              DESIGN.md, DESIGN-TH.md, GLOSSARY.md, PROPOSAL.md
reports/           training, drift, gate decision, cost, model card, the demo
```

`src/airquality/` is a six-hour PM2.5 nowcast taken as far as 155,109 versioned readings, a
profile, and a quality screen that found five faulty sensors — including one reporting a
constant 1,680 µg/m³ for eight days while producing fresh timestamps. It is kept because
the alternative considered is part of the reasoning, and its 23 tests still pass.

Design and methodology, with what breaks without each step:
[`docs/DESIGN.md`](docs/DESIGN.md) · [ภาษาไทย](docs/DESIGN-TH.md) ·
[glossary](docs/GLOSSARY.md)

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
4. **In the air quality work**, a sensor stuck at 1,680 µg/m³ for eight days passed every
   freshness check, because it kept reporting current timestamps. Freshness and
   plausibility are different questions.

---

## What is not done

- **Not deployed.** Every cost figure is projected from Lab 5's verified rates, not billed.
- **No registered model**, because the gate refuses the current one. Correct, and the honest
  next step is training on a recent window rather than tuning harder.
- **No group-fairness measurement.** Noted in the [model card](reports/model-card.md)
  rather than omitted.
