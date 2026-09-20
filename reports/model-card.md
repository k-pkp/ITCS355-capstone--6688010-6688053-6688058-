# Model card — call-list ranker

**Status: not registered.** The current candidate scores 1.34× lift against a 1.80× baseline
and the evaluation gate refuses it (`reports/bank-gate-decision.json`).

**What it does.** Ranks a bank's customer contact list so agents call the most promising
people first. It produces an *order*, not a decision: nothing is approved, denied or priced
by it, and the cost of an error is an unwanted phone call.

**Intended use.** One nightly batch, published before 06:00, read by a campaign supervisor
exporting the day's calls at 08:00.

**Training data.** UCI Bank Marketing, `bank-additional-full` — 41,188 rows from a
Portuguese telephone campaign, May 2008 to November 2010, CC BY 4.0 (Moro, Rita & Cortez
2014). Split in stored campaign order, never shuffled.

**Metrics — lift at a 500-call budget**, because accuracy misleads here: the base rate is
11.3%, so predicting "no" for everyone is 88.7% accurate and produces no call list.

| Ranking | Subscriptions in top 500 | Lift |
|---|--:|--:|
| Call in file order | 32 | 0.21× |
| This model | 207 | 1.34× |
| Sort by `euribor3m` alone | 278 | 1.80× |

**Limitations.**
*It loses to a single column* — sorting by the Euribor rate ranks better than the model
does, which is why nothing is registered.
*It was trained on a different world* — the training window has a 4.8% subscription rate and
the test window 30.8%; the campaign ran through the 2008 financial crisis.
*It must never be evaluated on a random split* — a random 50/50 reports 11.4% against 11.1%
and hides the shift entirely.
*`duration` is excluded and must stay excluded* — the most predictive column records how
long the call lasted, unknown when the list is built; including it appears to raise lift to
2.17×, all of it unavailable in production.
*`pdays` 999 is a sentinel, not a duration*, in 96.3% of rows.

**Ethical considerations.** The model orders who is called first, so its harm is an unwanted
call rather than a denied service. It nonetheless uses `age`, `job`, `marital` and
`education`, and a ranking that systematically deprioritised a group would give that group
less access to a product. **We have not measured group fairness.** That is a gap, stated
rather than omitted, and it is the first thing to add if this went anywhere real.

**When not to trust it.** While the drift report is alerting — at the time of writing, 6 of
7 monitored columns are above threshold. When the freshness gate has refused, in which case
there is no list. And for any question other than call ordering: it does not estimate
deposit size, suitability, or anything about an individual.
