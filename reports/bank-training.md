# Training report — call-list ranker

Seed 20260101. Split in stored campaign order: train 24,712 · validation 8,237 · test 8,239.
Trained on the most recent 4,000 rows before the test period.

subscribe rate: train 4.8% -> test 30.8% (6.4x). A ratio near 1.0 on this dataset means the rows were shuffled and the split is invalid.

## Ranked inside one contact month

This is the measurement the deployed job is judged by. It ranks the calls made within a single month against each other, because that is the only comparison the job is ever asked to make — it receives one export and decides who in that export to call first.

| Ranking | Lift, weighted across months | Worst month | Months measured |
|---|--:|--:|--:|
| model | 1.34x | 1.25x | 13 |
| baseline file order | 0.81x | 0.64x | 13 |
| baseline euribor | 0.96x | 0.41x | 13 |

### Month by month

| Month block | Rows | Model | euribor3m |
|---|--:|--:|--:|
| may | 3,275 | 1.25x | 1.02x |
| jun | 715 | 1.25x | 0.84x |
| aug | 770 | 1.30x | 0.89x |
| sep | 267 | 1.55x | 0.80x |
| oct | 447 | 1.48x | 1.24x |
| nov | 357 | 1.44x | 1.37x |
| mar | 264 | 1.52x | 0.88x |
| may | 212 | 1.34x | 0.84x |
| jun | 229 | 1.35x | 0.84x |
| jul | 311 | 1.32x | 0.87x |
| aug | 233 | 1.48x | 0.41x |
| sep | 303 | 1.74x | 1.05x |
| oct | 204 | 1.48x | 0.77x |

## Ranked across the whole test period at once

Kept because the gap between this table and the one above is the main finding of the project, not an embarrassment to be tidied away. Ranking the whole period rewards a ranking for sorting the calendar — information the job does not have, because every customer in one export was contacted at roughly the same time.

| Ranking | Subscriptions in top | Hit rate | Lift over random |
|---|--:|--:|--:|
| model | 304 | 60.8% | 1.97x |
| baseline file order | 32 | 6.4% | 0.21x |
| baseline euribor | 278 | 55.6% | 1.80x |

The test period's base rate is 30.8%, so calling 500 people at random yields about 154 subscriptions.

Accuracy is deliberately not reported as a headline. At this base rate a model that predicts 'no' for everybody is 88.7% accurate and produces no call list.

## What the leakage column would appear to buy

A second model trained on the same rows with `duration` included reaches **2.86x** within-month lift against the deployed model's **1.34x**.

That difference is not available at prediction time. `duration` is how long the call lasted, and the call has not happened when the list is built. The second model is never registered and never deployed; it exists to put a number on the trap, because 'duration is leakage' is an assertion and this is an argument.

`tests/bank/test_features.py::test_duration_never_reaches_the_model` is what keeps it out.
