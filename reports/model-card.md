# Model card — call-list ranker

## What it does

Ranks a bank's customer contact list so that agents call the people most likely to subscribe
to a term deposit first. It produces an **order**, not a decision: nothing is approved,
denied or priced by this model, and no customer is treated differently other than in what
order they are telephoned.

## Status

**Not registered.** The current candidate scores 1.34× lift against a baseline of 1.80×,
and the evaluation gate refuses it. See `reports/bank-gate-decision.json`.

## Intended use

| | |
|---|---|
| User | A campaign supervisor exporting tomorrow's call list |
| Frequency | Once nightly, published before 06:00 |
| Input | The day's customer export, 20 columns, one row per customer |
| Output | The top N customers by score, ranked |

## Training data

UCI Bank Marketing, `bank-additional-full` variant — 41,188 rows from a Portuguese bank's
telephone campaign, **May 2008 to November 2010**. Licensed CC BY 4.0. Cited as Moro, Rita
and Cortez (2014), DOI 10.24432/C5K306.

Split in stored campaign order: the earliest 60% trains, the latest 20% tests. Never
shuffled — see limitations.

## Metrics

Reported as **lift at a 500-call budget**: of the first 500 customers called, how many
subscribe, against calling 500 at random.

| Ranking | Subscriptions in top 500 | Lift |
|---|--:|--:|
| Call in file order | 32 | 0.21× |
| This model | 207 | 1.34× |
| Sort by `euribor3m` alone | 278 | 1.80× |

**Accuracy is deliberately not reported.** The base rate is 11.3%, so a model predicting
"no" for every customer is 88.7% accurate and produces no call list at all.

## Limitations

**It loses to a single column.** Sorting customers by the three-month Euribor rate ranks
them better than this model does. That is the current state, recorded rather than hidden,
and it is why nothing is registered.

**It was trained on a different world.** The training window has a 4.8% subscription rate
and the test window has 30.8%. The campaign ran through the 2008 financial crisis, and the
model learned conditions that no longer hold. This is the central limitation and the reason
the project monitors drift.

**It must never be evaluated on a random split.** A random 50/50 split reports 11.4% against
11.1% and hides the shift entirely. `tests/bank/test_splits.py` enforces this.

**`duration` is excluded and must stay excluded.** The most predictive column in the dataset
records how long the call lasted, which is unknown when the list is built. Including it
appears to raise lift from 1.34× to 2.17×, all of it unavailable in production.

**`pdays` is a sentinel, not a duration.** 999 means "never previously contacted" in 96.3%
of rows. It is split into a flag and a day count before the model sees it.

## Ethical considerations

The model ranks who is called first, so its cost of error is an unwanted phone call, not a
denied service. It is still a ranking over people, and two things follow.

**Protected-ish attributes are present.** `age`, `job`, `marital` and `education` are used.
A ranking that systematically deprioritises a group would give that group less access to a
product, which is a smaller harm than denial but is not nothing.

**We have not measured group fairness.** No per-group lift comparison has been run. That is
a gap, stated here rather than omitted, and it is the first thing to add if this were going
anywhere real.

## When not to trust it

- When the drift report is alerting, which at the time of writing it is: 6 of 7 monitored
  columns are above the PSI threshold.
- When the freshness gate has refused, in which case there is no list to trust.
- For any question other than call ordering. It does not estimate how much a customer will
  deposit, whether they should be offered a product, or anything about an individual.
