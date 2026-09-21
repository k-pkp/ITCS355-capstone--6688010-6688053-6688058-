# Cost report

Rates verified against the Cloud Billing Catalog for `asia-southeast1` during Lab 5 and
reused unchanged. Converted at 1 USD = 32.921586 THB.

## 1. Estimate, made before building

**4.60 THB per month.** The forecast is below, and section 3 compares it with what the
design actually implies.

## 2. What the system costs to run

| Line | Basis | THB / month |
|---|---|--:|
| Nightly scoring batch | 30 runs × ~60 s on spot `e2-standard-4` at 3.860 THB/h | 1.93 |
| Weekly retraining | 4 runs × ~3 min on spot | 0.77 |
| Object storage | dataset, DVC remote, published call lists | ~0.20 |
| Container registry | one image, retention policy on untagged versions | ~1.70 |
| Monitoring, alerting, scheduler | 6 custom metrics, one policy, one schedule | 0.00 |
| **Total** | | **~4.60** |

## 3. The decision that dominates the bill

The entire cost argument of this project is one choice, and it is worth stating as a
comparison rather than as a total:

| Serving pattern | THB / month | Ratio |
|---|--:|--:|
| Always-on managed endpoint, `n1-standard-4` | ~6,400 | 1,400× |
| **Nightly batch on spot (chosen)** | **1.93** | 1× |

An endpoint bills **8.889 THB per hour whether or not anything calls it**. This workload is
41,188 predictions once a day — 0.48 per second averaged out — and nobody waits on any of
them: agents read the list at 08:00 whether it was computed at 02:00 or at 07:59.

Buying an endpoint here would cost roughly 1,400 times more to deliver a result nobody
reads any sooner.

## 4. Cost per 1,000 predictions

41,188 customers scored per run at 0.064 THB gives **0.0016 THB per 1,000 predictions**.

That number is almost meaningless on its own, and it is included because the brief asks for
it. Three utilisation assumptions would produce three different answers, and none of them
would change any decision: the workload is a fixed nightly batch, so cost scales with the
number of runs and not with utilisation at all.

The figure that does change decisions is the one in section 3.

## 5. What Lab 5 taught that this project applies from day one

**The registry is a cost, and debugging is what grows it.** In Lab 5 the container registry
reached 3.17 GB and became the second largest line in the bill. 0.9 GB of that arrived in a
single afternoon, from pushing the same tag three times while fixing a pipeline — each push
left the previous version behind as an untagged image. A debugging session is a storage
cost.

So this project sets a retention policy on untagged versions before the first image is
pushed, rather than after discovering the bill.

**Budget the thing that bills by the hour.** Everything else on this list is rounding error.
In Lab 5 a Vertex endpoint accounted for 46% of the entire project bill for 1.45 hours of
existence, while every training job, every image and every byte of storage together came to
less.

## 6. One optimisation, applied

**Spot compute for both the nightly batch and retraining**, at 3.860 THB/h against 7.076
on-demand — a 45% discount.

The trade is that Google can reclaim the machine with little warning. It is acceptable here
because the job is idempotent and short: a reclaimed run is re-run from the same input and
produces the same list, and the schedule has two hours of slack before the 06:00 deadline.

A job that could not be safely re-run would not be a candidate for spot, and the discount
would be worth nothing.

## 7. Honest limits

No figure here has been reconciled against an invoice. Billing export is not configured on
this project, so every number is rebuilt from rates verified against the Billing Catalog
and quantities taken from what the jobs actually did. That is measurement, not accounting,
and the two can differ.

The quantities are no longer estimates from local runs. The jobs run on the schedule, and
the recorded scoring runs took 10.65 s, 3.03 s and 12.31 s on spot `e2-standard-4` at 3.860
THB/hour. Thirty runs a month at the slowest of those is **1.93 THB/month** for the scorer,
which is the figure in section 3 — the estimate made before building turned out right for
the reason it was made, not by luck: this design's cost is dominated by how long a machine
exists, and the machine exists for about ten seconds a day.

**There are now three scheduled jobs, not one.** The replay feeder at 01:50 and the
realised-lift measurement at 02:10 each cost about the same as the scorer, so the honest
monthly figure is roughly **5.8 THB**, not 1.93. Each is a separate Vertex job rather than
three steps in one, and that choice costs about 3.9 THB a month: if the feeder were a step
inside the scorer, a feeder failure would fail the whole run instead of leaving a stale
input for the freshness gate to refuse. Four baht a month is what it costs for the gate to
be a real control rather than a demonstration.

Against the always-on endpoint's ~6,400 THB/month, three jobs and one job round to the same
number.

The dashboard, the alert policy and the six custom metric series are inside the free
allowance. The container images are not: the registry holds six versions of this image, and
Lab 5 measured registry storage at 38% of that project's bill because nothing ever deletes
an old image.
