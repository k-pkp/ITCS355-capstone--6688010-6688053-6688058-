# Model card — call-list ranker

**Status: registered**, `bank-call-list-ranker` version 1, with nine lineage fields
(`reports/bank-registry.md`). An earlier candidate was refused by the gate at 1.34× against
a 1.80× baseline; that comparison ranked the whole test period at once, which credited the
baseline with sorting the calendar — information the nightly job does not have. Working:
`reports/bank-export-evaluation.md`.

**What it does.** Ranks a bank's customer contact list so agents call the most promising
people first. It produces an *order*, not a decision: nothing is approved, denied or priced
by it, and the cost of an error is an unwanted phone call.

**Intended use.** One nightly batch, published before 06:00, read by a campaign supervisor
exporting the day's calls at 08:00.

**Training data.** UCI Bank Marketing, `bank-additional-full` — 41,188 rows from a
Portuguese telephone campaign, May 2008 to November 2010, CC BY 4.0 (Moro, Rita & Cortez
2014). Split in stored campaign order, never shuffled.

**Training window.** The most recent 4,000 rows before the test period, not all 24,712.
The campaign spans a financial crisis and older rows describe a different world. The window
size was chosen on the validation period.

**Metrics — lift within one contact month**, at the supervisor's call share. Accuracy
misleads here: the base rate is 11.3%, so predicting "no" for everyone is 88.7% accurate
and produces no call list. The measurement is taken inside a month because that is the only
comparison the job makes — it ranks one export, never the whole campaign.

| Ranking, within one month | Lift | Worst month |
|---|--:|--:|
| Call in file order | 0.81× | 0.64× |
| Sort by `euribor3m` alone | 0.96× | 0.41× |
| **This model** | **1.34×** | **1.25×** |

**Limitations.**
*Its skill does not survive a regime break* — measured, not supposed. On the validation
period, which is the 2008 crisis onset, the same model scores 1.07× within month and falls
below 1.0 in two of its four months, meaning those months' call lists were worse than
calling people in no particular order. It works in a stable rate environment. The drift
monitor exists to say when that stops being true.
*It was trained on a different world* — the training window has a 4.8% subscription rate and
the test window 30.8%; the campaign ran through the 2008 financial crisis.
*It must never be evaluated on a random split* — a random 50/50 reports 11.4% against 11.1%
and hides the shift entirely.
*`duration` is excluded and must stay excluded* — the most predictive column records how
long the call lasted, unknown when the list is built; including it appears to raise
within-month lift from 1.34× to 2.86×, all of it unavailable in production.
*`pdays` 999 is a sentinel, not a duration*, in 96.3% of rows.
*The data is historical and the system is not live* — the campaign ended in November 2010.
Scoring runs against a slice of that same file rather than a new export, and the drift the
monitoring detects is a real shift being replayed rather than one observed now.

**Ethical considerations.** The model orders who is called first, so its harm is an unwanted
call rather than a denied service. It nonetheless uses `age`, `job`, `marital` and
`education`, and a ranking that systematically deprioritised a group would give that group
less access to a product. **We have not measured group fairness.** That is a gap, stated
rather than omitted, and it is the first thing to add if this went anywhere real.

**When not to trust it.** While the drift report is alerting — at the time of writing, 6 of
7 monitored columns are above threshold. When the freshness gate has refused, in which case
there is no list. And for any question other than call ordering: it does not estimate
deposit size, suitability, or anything about an individual.
