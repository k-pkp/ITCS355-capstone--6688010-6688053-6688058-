# ITCS355 Capstone — Proposal

**Team:** [name 1] · [name 2] · [name 3]  ·  **Submitted:** end of Session 3

## Problem, and who would use it

Predict PM2.5 for the next six hours at each monitoring station, so that a decision which is
currently made by looking out of the window can be made from a number.

The user we are designing for is whoever decides whether an outdoor activity goes ahead: a
school deciding about afternoon sport, a parent deciding whether to walk a child to school,
a site supervisor deciding whether outdoor work continues. They do not want a map of what
the air is like now — they can already see that. They want to know whether it will be worse
by three o'clock, while there is still time to change the plan.

This matters locally. Northern Thailand's burning season pushes PM2.5 far past the safe
threshold for weeks at a time, and the difference between acting at noon and reacting at
three is the entire value of the system.

## Dataset and licence

**OpenAQ**, the open air-quality aggregator, via its v3 API. We pull historical hourly
PM2.5 for a fixed set of Thai stations to train, and the same endpoint on a schedule to
serve.

**The licence is per provider, not per platform, so we checked rather than assumed.** Of the
618 Thai PM2.5 stations OpenAQ lists:

| Provider | Stations | Licence |
|---|--:|---|
| AirGradient | 346 | **CC BY 4.0** |
| Air4Thai (government monitors) | 263 | none stated |
| Clarity | 3 | CC0 1.0 |
| AirNow | 1 | US Public Domain |

We are using **40 AirGradient stations, all CC BY 4.0**, and we attribute both AirGradient
and OpenAQ, which OpenAQ's terms require when their service is used to obtain the data. The
station list is pinned in `data/stations.json` with each station's provider and licence
recorded next to it, so the dataset can be rebuilt exactly and the licence question has a
file-based answer rather than a remembered one.

**We are deliberately not using the government Air4Thai monitors**, even though they are the
more authoritative source, because OpenAQ states no licence for them. An unstated licence is
not a permissive one, and we would rather train on data we can defend than on data that is
merely available. Our station search refuses unstated licences by default; including them
requires an explicit flag.

**What this costs us, stated plainly:** AirGradient are low-cost community sensors, not
reference-grade instruments, so the readings are noisier than Air4Thai's would be. Accuracy
carries no marks here, and low-cost sensors drop out more often than government ones — which
makes the failure this project is built around more representative, not less.

## Latency and freshness

Nobody waits on this prediction, so there is no latency requirement worth defending. Every
requirement here is about **freshness**, which is a different question and the one that
actually governs the design.

| Requirement | Target | Why |
|---|---|---|
| Input age at scoring time | ≤ 90 minutes | Stations report hourly and arrive late; 90 minutes tolerates one slow arrival |
| Forecast published | Within 10 minutes of the hour | A six-hour forecast published 40 minutes late is a five-hour forecast |
| Forecast horizon | 6 hours, hourly steps | Long enough to change an afternoon plan, short enough that persistence is not the whole answer |
| Staleness refusal | **> 2 hours old**, per station | Measured, not guessed: 99.5% of consecutive readings are exactly 1 hour apart, and gaps beyond 2 hours occur in 0.30% of intervals |

## Serving pattern, and why

**Scheduled batch, hourly.** Not an endpoint.

A forecast that updates hourly cannot be more useful than hourly, however it is served. An
always-on managed endpoint costs **8.889 THB per hour whether or not anything calls it** —
about 6,400 THB a month to answer a question that changes twelve times a day. Measured
against our own Lab 5 figures, the same work as a scheduled batch job on spot compute:

| Cadence | Runs/month | Billed compute | THB/month |
|---|--:|--:|--:|
| Every 30 minutes | 1,440 | 24.0 h | 92.64 |
| **Hourly (chosen)** | **720** | **12.0 h** | **46.32** |
| Every 3 hours | 240 | 4.0 h | 15.44 |
| Daily | 30 | 0.5 h | 1.93 |

We are choosing the hourly row knowingly, and it is not the cheapest. Three-hourly would
save 31 THB a month and would also mean a forecast could be two hours stale at the moment
someone reads it, which breaks the freshness target above. Daily is 24× cheaper and useless
for this problem — the whole point is intra-day change.

**The cost is dominated by the number of runs, not the work.** Each run is about a minute of
actual compute; at 720 runs a month we are largely paying per-job overhead. That is the
honest trade for freshness here, and it is the kind of thing that is invisible until you
count the jobs.

## The deliberate failure we are designing for

**A station goes offline and its last reading is carried forward.**

This is not hypothetical — sensor networks drop stations constantly, for power cuts,
maintenance and network faults. The failure is that nothing in a normal pipeline notices.
The ingest returns 200 OK. The row count is unchanged, because the last known value is still
there. The score distribution looks normal. The model produces a confident forecast. The map
shows clean air at a location where there is no data at all, and it shows it during exactly
the episode when someone is checking whether it is safe to go outside.

**The control:** a per-station staleness gate that reads each measurement's own timestamp —
not the HTTP status — before scoring. A station whose newest reading is older than **two
hours** is **excluded from the forecast and rendered as "no data"**, and the exclusion count
is emitted as a monitored metric with an alert when it rises.

**The two-hour threshold is measured rather than chosen.** In six months of history, 99.5%
of consecutive readings are exactly one hour apart, and only 0.30% of intervals exceed two
hours. So the gate is quiet during healthy operation, which is the property that decides
whether anyone leaves it switched on. Our first draft of this proposal said three hours; the
data says two catches an outage an hour sooner at a false-alarm cost of 0.07 percentage
points.

**The data already contains the failure we are designing for.** Station 2457250 reported 135
readings above 1000 µg/m³ in early May — during a month whose median is 12.5 — and then went
silent for 57 days. Station 2142493 reports an exact zero 17.8% of the time, which is not a
possible outdoor measurement. We are not inventing a broken sensor for the demo; we have
several, and the honest system has to survive them.

We chose this failure because the wrong output is more dangerous than no output, and because
it is invisible to every check that a working pipeline normally has. We will demonstrate it
live by freezing one station's feed, showing the forecast it produces without the gate, then
showing the gate refusing and alerting.

**A second signal we get for free:** burning season is a genuine distribution shift, not an
injected one. Our Lab 4 drift detector runs on the same features, so the monitoring story has
a real seasonal shift to detect rather than a synthetic one.

## Rough cost estimate

Rates verified against the Cloud Billing Catalog for `asia-southeast1` during Lab 5.

| Line | Basis | THB / month |
|---|---|--:|
| Hourly scoring batch | 720 runs × ~60 s on spot `e2-standard-4` at 3.860 THB/h | 46.32 |
| Weekly retraining | 4 runs × ~3 min on spot | 0.77 |
| Object storage | measurements, DVC remote, published forecasts | ~0.30 |
| Container registry | one image, retention policy on untagged versions | ~1.70 |
| Monitoring, alerting, scheduler | custom metrics, one policy, one schedule | 0.00 |
| **Total** | | **~49** |

**Cost per 1,000 predictions:** each run forecasts 6 hours for ~40 stations = 240
predictions, at 0.064 THB per run — **0.27 THB per 1,000**. Higher than a daily batch would
be, for the reason given above: we are buying freshness, and freshness is priced per run.

The registry carries a retention policy deliberately. In Lab 5 ours reached 3.17 GB and
became the second largest cost in the project, entirely from rebuilds nobody cleaned up.

## Who owns what

| Area | Owner |
|---|---|
| Repository, pipeline and documentation | [name 1] |
| Review and presentation | [name 2] · [name 3] |

Work is tracked in the repository's commit history, so who did what is a matter of record
rather than of memory.

## What we are deliberately not doing

No deep learning and no spatial interpolation between stations. Model accuracy carries no
marks, so the model is a gradient-boosted tree over lagged readings, hour of day and station
id. Our baseline is persistence — tomorrow's value is today's value — and we stop tuning the
moment we beat it by more than seed noise.

We are also not building a map UI. The deliverable is a published forecast table and the
operational system around it; a front end would consume time that the failure demo needs.

## Open question for approval

We intend to pin a fixed list of Thai station ids. If the instructor would prefer a different
geography or a wider station set, that changes the licence set we must record, and we would
rather know before we build than after.
