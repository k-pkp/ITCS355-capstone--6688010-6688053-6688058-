# "Your data is not live. How does it run day by day?"

The honest answer is that the campaign is **replayed**: a separate scheduled job publishes
the next slice of it every night, and the scoring job treats that slice as today's export.
The rows are real rows about real people who were really called. What is synthetic is only
the calendar.

## Why the question is a good one

Without this, the nightly job reads the same file every night and publishes the same call
list. "It runs every night" would mean "it runs the same night, nightly". Worse, three of
the project's controls could never actually fire:

- the **freshness gate** would never have a fresh input to pass
- the **drift numbers** would never move
- the **call list** would be identical every morning, so nothing downstream could notice
  anything at all

## How it runs

| Time (Asia/Bangkok) | Job | What it does |
|---|---|---|
| 01:50 | `itcs355-capstone-feeder` | publishes the next 600 rows of the held-out period as `capstone/incoming/contacts.csv` |
| 02:00 | `itcs355-capstone-nightly` | reads it, checks its age, contract and model, publishes a call list |

A cursor in the bucket — `capstone/state/replay-cursor.json` — records how far the replay has
reached. It lives in object storage rather than in the container, because the container is
new every night and a cursor that resets every night is not a cursor.

The replay draws **only from the 8,239 rows the model never trained on**. Replaying rows the
model was fitted to would produce a system that looks better every night for the worst
possible reason. At 600 rows a night that is 14 nights of operation.

## Two jobs, not one, on purpose

The feeder could have been a first step inside the scoring job. Keeping it separate is what
makes the freshness gate a real control rather than a demonstration:

**If the feeder fails, nothing rewrites the export. It ages past 24 hours. The scorer
refuses.** That is the failure the whole project is built around — an upstream export that
did not arrive — happening for real, rather than being simulated by editing a timestamp.

The same holds at the end of the replay. When the held-out period runs out the feeder
publishes nothing and says so, rather than looping back to the start:

```
the replay is exhausted: no export was published.
The scoring job will refuse on staleness within 24 hours, which is what should
happen when an upstream stops sending.
```

## The one thing a replay can do that live data cannot

A live campaign publishes a list, the agents work it, and the outcomes arrive over the
following weeks. "Was last night's list any good?" has no answer until long after it stops
being useful. Lab 3 hit the same wall: the label there arrives seven days late, which is why
the canary had to be judged on a label-free proxy that turned out too weak to see anything.

**The replay already knows.** The campaign finished in 2010, so every replayed row carries
the answer the customer gave, and `scripts/measure_yesterday.py` scores the published list
the next morning:

```
call list for 2026-09-21
  export:  600 customers, 44 subscribed (7.3%)
  called:  100 customers, 10 subscribed (10.0%)
  realised lift: 1.36x
  +2.7 subscriptions against calling the same 100 people at random
```

That 1.36× is not a held-out test score. It is what the model *actually did* to a published
list, measured against what actually happened, and it goes on the same dashboard as the
inputs. **A monitoring loop that closes same-day is the one respect in which historical data
beats live data**, and it is the respect that matters for demonstrating monitoring.

The model never sees that column. `features.EXCLUDED_COLUMNS` drops the target before
anything is scored, which is what makes the measurement a measurement rather than a circle.

## Calling a share, not a number

The replayed night is 600 customers, not the real campaign's ~3,000, so that a fortnight of
operation can be watched rather than waited for. The call budget therefore scales with the
export — `--call-share 0.1667`, the same 500-out-of-3,000 the evaluation measures at —
rather than staying at a fixed 500.

A fixed 500 against an export of 600 would mean calling five customers in six, and a list
that calls almost everybody has a lift of exactly 1.0 by definition. The system would have
reported success while doing nothing.

## What this is not

It is not live data, and the README says so. A replay cannot surprise anyone: the shift it
walks through already happened, and we know where it goes. What it demonstrates is that the
**operational** system runs day after day, refuses when it should, and can measure its own
output — which is what the course asks for. The brief asks for deployed inference "online or
batch", not for a live feed.
