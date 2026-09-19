# Training report — call-list ranker

Seed 20260101. Split in stored campaign order: train 24,712 · validation 8,237 · test 8,239.

subscribe rate: train 4.8% -> test 30.8% (6.4x). A ratio near 1.0 on this dataset means the rows were shuffled and the split is invalid.

## Ranked against the baselines

Measured on the held-out final period, at a call budget of 500.

| Ranking | Subscriptions in top | Hit rate | Lift over random |
|---|--:|--:|--:|
| model | 207 | 41.4% | 1.34x |
| baseline file order | 32 | 6.4% | 0.21x |
| baseline euribor | 278 | 55.6% | 1.80x |

The test period's base rate is 30.8%, so calling 500 people at random yields about 154 subscriptions.

Accuracy is deliberately not reported as a headline. At this base rate a model that predicts 'no' for everybody is 88.7% accurate and produces no call list.

## What the leakage column would appear to buy

A second model trained with `duration` included scores **2.17x** lift against the deployed model's **1.34x**.

That difference is not available at prediction time. `duration` is how long the call lasted, and the call has not happened when the list is built. The second model is never registered and never deployed; it exists to put a number on the trap, because 'duration is leakage' is an assertion and this is an argument.

`tests/bank/test_features.py::test_duration_never_reaches_the_model` is what keeps it out.
