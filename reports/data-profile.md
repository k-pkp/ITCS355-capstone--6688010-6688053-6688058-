# Data profile

Measured from the downloaded readings by `scripts/profile_data.py`. Every number a later decision depends on is here, so that the decision can cite it.

## Shape

- Stations: **39**
- Readings: **155,109**
- Window: **2026-03-23** to **2026-09-19**
- Coverage: **92.1%** of every possible station-hour
- Hours per station: min **2,274**, median **4,253**, max **4,307**

## Gaps between readings

This section decides the staleness threshold, which the proposal had guessed at.

- **99.5%** of consecutive readings are exactly one hour apart.
- Gaps longer than **2h**: 0.30% of intervals (466 of 155,070)
- Gaps longer than **3h**: 0.23% of intervals (353 of 155,070)
- Gaps longer than **4h**: 0.19% of intervals (289 of 155,070)
- Gaps longer than **6h**: 0.15% of intervals (236 of 155,070)
- Gaps longer than **12h**: 0.10% of intervals (162 of 155,070)
- Gaps longer than **24h**: 0.04% of intervals (69 of 155,070)
- Longest single gap: **1374 hours** (57.2 days)

**Chosen threshold: 2 hours.** 2 hours, the smallest whole hour at which normal operation trips the gate on only 0.30% of intervals.

A station whose newest reading is older than this is excluded from the forecast and reported as no data. The threshold is set from the gap distribution rather than chosen, because a gate that fires during healthy operation gets switched off, and a gate nobody trusts is worse than no gate at all — it also claims that someone is watching.

## Values that cannot be right

- Negative readings: **0**
- Exactly zero: **1747** (1.13%) — a true zero is implausible outdoors and usually means a sensor fault
- Above 1000 µg/m³: **152** — physically possible in a severe episode, but worth confirming before training on it
- Duplicate (station, hour) pairs: **0**

## The baseline any model must beat

Persistence: predict that the value in N hours equals the value now.

- Persistence at **+1h**: mean absolute error **5.41** µg/m³, median **1.40**
- Persistence at **+3h**: mean absolute error **11.05** µg/m³, median **2.90**
- Persistence at **+6h**: mean absolute error **16.25** µg/m³, median **3.90**

Model accuracy carries no marks in this project, but a model that loses to persistence should not be deployed, and knowing the number in advance stops a worse model being mistaken for progress.

## Monthly PM2.5

| Month | Median | Max | Readings |
|---|--:|--:|--:|
| 2026-03 | 76.1 | 769 | 7,186 |
| 2026-04 | 72.0 | 1690 | 25,909 |
| 2026-05 | 12.5 | 1700 | 26,934 |
| 2026-06 | 5.6 | 508 | 26,550 |
| 2026-07 | 7.7 | 781 | 26,639 |
| 2026-08 | 5.6 | 944 | 25,785 |
| 2026-09 | 9.8 | 914 | 16,106 |

**18.3%** of all readings exceed Thailand's 24-hour standard of 37.5 µg/m³.

The March and April figures are burning season. This is a real distribution shift, present in the data without anyone injecting it, and it is what the drift detection in this project has to catch.
