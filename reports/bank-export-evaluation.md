# What the gate was measuring, and why it was the wrong thing

The gate refused the model. It was right to, given what it measured — and what it measured
was a question the deployed job is never asked. Finding that out changed the answer.

This report is the working. Every number was produced by running the code.

---

## The refusal

```
lift 1.34 does not clear the best baseline (euribor3m, 1.80) by the required 0.05;
it needs 1.85
```

The comparison ranked all 8,239 rows of the held-out test period at once and counted
subscriptions in the top 500. Ranking by the single column `euribor3m` beat the model
comfortably.

That is a strange result worth stopping on rather than tuning past. `euribor3m` is the
three-month interbank rate. It is identical for everyone contacted in the same week. It
says nothing whatsoever about whether *this* customer, rather than that one, will
subscribe.

## Why one column won

Because the measurement let it answer a different question.

The test period runs from a time when euribor was about 1.30 down to about 0.63, and
subscriptions rose steeply as the rate fell. Sorting 8,239 customers by `-euribor3m` sorts
them, near enough, **by date** — and putting the latest months first is a winning strategy
when the latest months are when people said yes.

The deployed job never gets that opportunity. It receives one export, of customers to be
called next, who were all contacted at about the same time. Inside that export euribor
barely moves.

So the whole-period measurement was scoring a baseline on its ability to sort the calendar,
and then holding the model to it.

## Measured: the baseline's advantage is entirely between months, not within them

Ranking inside single contact months, on the test period, using the final model:

| Ranking | Lift, weighted across 13 months | Worst month |
|---|--:|--:|
| **model** | **1.34x** | 1.25x |
| `euribor3m` | 0.96x | 0.41x |
| file order | 0.81x | 0.64x |

`euribor3m` at 0.96x is not a strong baseline that the model narrowly beats. It is **no
better than calling customers in no particular order**, which is what a column that is
constant within a batch should be.

Sweeping the block size shows the advantage draining away as the block shrinks — the model
trained on 16,000 rows, blocks taken in campaign order:

| Rows ranked together | Model | `euribor3m` |
|--:|--:|--:|
| 8,239 (the whole period) | 1.596x | **1.803x** |
| 4,000 | 1.310x | 0.999x |
| 3,000 | 1.175x | 1.131x |
| 2,000 | 1.290x | 0.975x |
| 1,000 | 1.284x | 0.965x |
| 500 | 1.298x | 1.025x |

One row of that table is the old gate's entire evidence.

---

## The second fix: train on a recent window

The campaign spans a financial crisis. Training on all 24,712 early rows means fitting
mostly to 2008–2009, when 4.8% of customers subscribed, and then ranking customers in a
2010 world where 30.8% did.

Window sizes were swept on the **validation** period. The test period was not involved in
this choice.

| Training window | Within-month lift on validation |
|--:|--:|
| **last 4,000 rows** | **1.071x** |
| last 8,000 | 0.970x |
| last 12,000 | 0.832x |
| last 16,000 | 0.881x |
| last 20,000 | 0.855x |
| all 24,712 | 0.775x |

Less history is better, monotonically, which is the shape a regime change produces.

The window alone — before any change to the measurement — lifts the **whole-period** score
from 1.34x to **1.97x**, which clears the old gate's 1.85x requirement. So the model was
genuinely undertrained *and* the measurement was genuinely wrong, and either fix alone
would have changed the verdict.

---

## A hypothesis that was tested and was wrong

If the macro columns describe the month rather than the customer, removing them should
sharpen ranking *inside* a month while weakening it across months.

| | Test, within export | Validation, within export |
|---|--:|--:|
| with macro columns | 1.246x | 0.912x |
| without macro columns | 1.243x | 0.858x |

No improvement, slightly worse. The columns are kept. Recorded because a project that only
reports the experiments that worked is reporting a selection, not a result.

---

## The limits, stated plainly

**A month is not a night.** The dataset carries no date, only a month name, so the smallest
honest block is a month's calls — bigger than a real nightly export. Inside a real export
`euribor3m` would be even flatter than it is here, so the baseline's true score is if
anything *below* the 0.96x measured.

**On the validation period the model does not beat the baseline.** Within month it reaches
1.071x against the baseline's 1.155x — and in two of the four validation months it ranks
*below* 1.0, worse than random. The validation period is the crisis onset, the sharpest
regime break in the data. The model is trained on the window before it, and that window
does not describe it.

That is not a caveat to be filed away: it is the measured statement that **this model's
skill does not survive a regime break**. It is in the model card as a known limit, and it
is why the drift monitor exists. What is deployed is a model that works in a stable rate
environment and a monitor whose job is to say when that stops being true.

**The gate now also checks the worst month, not only the average.** A mean of 1.4 built
from one month at 2.1 and three at 0.8 is three months of call-centre time spent worse than
guessing. The current model's weakest month is 1.25x, and every one of the 13 months is
above 1.0.

---

## What the gate decided in the end

```
candidate  within month: lift 1.34x across 13 months, worst month 1.25x
baseline   file_order: lift 0.81x
baseline   euribor3m: lift 0.96x

GATE PASS
```

Registered as `bank-call-list-ranker` version 1, with lineage — see
[`bank-registry.md`](bank-registry.md) and [`bank-gate-decision.json`](bank-gate-decision.json).

---

## The lesson, which is the point of the project

The first gate was not broken. It ran, it computed correct arithmetic, it refused a model,
and it wrote its reasons to a file. Everything about it worked except the question.

A metric that is wrong in this way does not raise an error and does not look suspicious. It
looks like a disappointing model — and the natural response to a disappointing model is to
tune it, which would have spent days improving a number that was answering the wrong
question. The tell was not in the code. It was that **one column with no per-customer
information was winning**, which is the kind of result that should stop work rather than
prompt a retrain.
