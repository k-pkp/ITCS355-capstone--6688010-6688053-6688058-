# Demo runbook — 8 minutes, plus 5 of questions

15 marks, scored separately from the repository. The brief is blunt about it: *"Preparing
the system well and presenting it badly costs a third of the capstone."*

The brief also sets the running order, so this follows it exactly: the problem in 60
seconds, the architecture, a live demo, the failure and what it revealed, the costs, and
what another week would buy.

---

## Before you start

Run this once, an hour before. It takes about a minute and it means nothing is built live.

```bash
cd ~/MU/MLOD/itcs355-capstone
python scripts/train_bank.py          # writes the model the demo scores with
python scripts/demo_stale_input.py    # confirms the failure demo still holds
pytest -q                             # 82 passing
```

Then prepare the inputs you will score in front of people:

```bash
mkdir -p /tmp/demo
python - <<'PY'
import pandas as pd
frame = pd.read_csv("data/bank/bank-additional-full.csv", sep=";").tail(2000)
frame.to_csv("/tmp/demo/today.csv", sep=";", index=False)
PY
cp /tmp/demo/today.csv /tmp/demo/yesterday.csv
touch -d "26 hours ago" /tmp/demo/yesterday.csv
```

**Have two terminals open**, both already in the project directory, font size large enough
to read from the back of the room. Have `reports/bank-gate-decision.json` open in an editor
in a third tab.

---

## Minute by minute

### 0:00 – 1:00 · The problem

Say it in plain words, no slides needed:

> A bank sells savings products by phone. Eleven per cent of calls succeed, so nearly nine
> in ten waste an agent's time. Every night we score tomorrow's customer list and publish it
> in order, best first. The supervisor exports it at eight in the morning.
>
> Nobody waits on a prediction. That one fact decides the whole architecture.

**Do not** explain the model. Nobody is grading it, and you have 60 seconds.

### 1:00 – 2:00 · The architecture

One sentence per box, on one slide or drawn on the whiteboard:

```
read input -> FRESHNESS GATE -> data contract -> features -> score -> publish
                                                                        |
                                                          metrics -> alert
```

> Nightly batch, not an endpoint. An always-on endpoint bills 8.889 baht an hour whether
> anyone calls it or not — about 6,400 baht a month to answer half a request a second that
> nobody is waiting for. The same work as a nightly batch costs 1.93.

### 2:00 – 4:30 · The live demo — the failure

This is the centre of the presentation. Run it, do not describe it.

**Terminal 1 — score today's file:**

```bash
python scripts/score_nightly.py --input /tmp/demo/today.csv
```

> Normal night. Five hundred customers published, scores in the usual range, exit zero.

**Terminal 1 — now yesterday's file, with the gate switched off:**

```bash
python scripts/score_nightly.py --input /tmp/demo/yesterday.csv --skip-freshness-gate
```

Let it finish. Then pause, and say the important sentence slowly:

> This also succeeded. Same row count. Same score distribution. No error. A dashboard
> watching rows, duration, score ranges or exit codes sees a completely healthy run.
>
> It published yesterday's list. In the morning, agents call the people they called
> yesterday, and nobody finds out until a customer complains about being called twice.

**Terminal 1 — the same file, with the gate on:**

```bash
python scripts/score_nightly.py --input /tmp/demo/yesterday.csv
```

> The gate reads the file's own modification time, not whether the read succeeded. Twenty-six
> hours old, over the twenty-four hour limit, so it publishes **nothing** and alerts.
>
> That is the design decision worth defending. A missing call list is noticed in ten minutes.
> A plausible wrong one is worked through for a day.

### 4:30 – 5:30 · What the failure revealed

> Building this found a second failure we had not designed for. In the earlier version of
> this project a sensor sat at the same reading for eight days while still sending fresh
> timestamps. It passed every freshness check, because freshness and plausibility are
> different questions and we were only asking one.
>
> That is why the contract sits behind the gate rather than instead of it.

If you have 20 seconds spare, add:

> Our drift detector also reported a column as perfectly stable while its values had moved
> so far that the old and new ranges do not overlap at all. A low score is exactly what a
> healthy column produces, so nothing downstream could have caught it.

### 5:30 – 6:30 · Honest results

Put this table up. Do not soften it.

| Ranking | Subscriptions in top 500 | Lift |
|---|--:|--:|
| Call in file order | 32 | 0.21× |
| Our model | 207 | 1.34× |
| **Sort by one column** | **278** | **1.80×** |

> Our model loses to sorting customers by the Euribor rate. The evaluation gate refuses to
> register it, which is the correct outcome and the first time the gate has been exercised
> by something real rather than by a test.
>
> The reason is the drift. The model trained on a period with a 4.8% subscription rate and
> was tested on one at 30.8% — the campaign ran through the 2008 financial crisis.

Show `reports/bank-gate-decision.json` on screen for three seconds. Move on.

### 6:30 – 7:15 · Costs

> About 4.60 baht a month. The number that matters is not the total, it is the comparison:
> 1.93 for a nightly batch against roughly 6,400 for an always-on endpoint, for a result
> nobody reads before eight in the morning.
>
> One thing we brought from the labs: the container registry grew to 3.17 gigabytes and
> became the second largest cost, almost entirely from pushing the same tag while debugging.
> A debugging session is a storage cost, so this project has a retention policy from day one.

### 7:15 – 8:00 · What another week would buy

Be specific and short. Three things, ten seconds each:

1. **Make the model beat the baseline** — train on a recent window instead of all history,
   which is the honest fix for the drift rather than tuning harder.
2. **Measure group fairness** — the model uses age, job, marital status and education, and
   we have not checked whether it deprioritises any group. It is named as a gap in the model
   card.
3. **Reconcile the cost against a real invoice** — every figure is projected from verified
   rates, not billed.

---

## The five minutes of questions

**Expect unexpected input.** The brief says so explicitly. Every one of these was tested,
and each refuses with a readable message rather than a stack trace:

| If they hand you | What happens |
|---|---|
| A file with a new job category | `unexpected_category: job contains ['influencer']` |
| A file missing a column | `required_columns: missing ['euribor3m']` |
| Ages of 1975 | `implausible_age: ages outside 17-100` |
| An empty file | `empty_input: the export contains no rows at all` |
| A file from last week | `STALE INPUT — published nothing` |

Offer it before they ask: *"If you have a file you would like to give it, I would like to
run it."* That turns their test into your demo.

### Questions you should have an answer ready for

**"Why not just use an endpoint?"**
Nobody reads the list before 08:00, so 6,400 baht a month buys nothing. If a supervisor ever
needed a score on demand, the same model behind an endpoint would be the change, and it
would cost about 3,300 times more per prediction.

**"Your model is worse than sorting by one column. Why deploy it?"**
We would not, and the gate does not let us. That is what it is for.

**"Why is the gate 24 hours?"**
The list is consumed once a day, so an input older than a day describes a day that has
already been worked through. In the earlier version of this project we set the equivalent
threshold from the measured gap distribution rather than by choosing it — 99.5% of readings
arrived an hour apart, so two hours was the limit that stayed quiet during healthy operation.

**"How do you know your tests actually work?"**
We disable a rule on purpose and check that exactly the expected tests go red, then restore
it. Disabling the negative-value rule turns two tests red; making the split shuffle turns
three more.

**"What would you do differently?"**
Measure the baseline first. We found out the model loses only after building it, and the
baseline took four lines.

---

## If something breaks live

The brief says crashing still scores partial credit **if your logging makes the cause
obvious within a minute**. So:

- Do not retype the command hoping it works. Read the error out loud.
- Every refusal path prints what refused and why. Point at that line.
- If a script genuinely crashes, say: *"That is a stack trace rather than a refusal, which
  means it is our bug and not a guarded path"* — and move on to the next section. Diagnosing
  live costs more marks than the crash did.

**Have `reports/stale-input-demo.md` open in a tab.** If the live run fails, it contains the
same demonstration already captured, and you lose ten seconds rather than the section.
