# Promotion: what connects an approved model to the one that runs

The gate decides whether a model *may* serve. Until this was added, nothing decided what
*does* serve: the job loaded whichever file sat at `reports/bank-model.joblib`, and the
image was built from whatever was on disk. "Which model is in production" was answered by a
build log.

Three checks close that, and each was proved by running it rather than by reading it.

## 1. The serving model must be the approved one

Registration writes the SHA-256 of the approved bytes to `reports/approved-model.json`,
which ships in the image. The job hashes the model it is about to load and refuses if they
differ.

A hash, not a version number: a version number is a label someone writes, a hash is a fact
about the file. Lab 5 pushed the same image tag three times in one afternoon and ended with
a tag naming code that was not inside the image.

**Proved** by training a different, perfectly valid model and putting it at the serving path:

```
UNAPPROVED MODEL — published nothing:
  the model at reports/bank-model.joblib is not the approved one.
  approved: 70b8a6117a187371… (registered version 2)
  serving:  46722e09154c67f4…
The gate approved a model and the image contains a different one.
```

Exit code 5, nothing published. With the approved model restored:

```
model 70b8a6117a187371… matches the approved one
published 500 customers
```

Nothing was wrong with the substituted model. It loaded, it scored, it would have published
a call list. It was simply not the one anybody approved — which is exactly the failure that
no amount of testing the model itself can catch.

## 2. A candidate must beat the model already serving

The gate compared against fixed baselines and never against the incumbent, so a model worse
than the one it replaces passed as long as it cleared `euribor3m`. Each release could be a
small step backwards while every release looked like a pass.

The incumbent is now **re-scored on the same test period** and handed to the gate as another
baseline — re-scored rather than read from its recorded lift, because two numbers produced
at different times from different data are not comparable.

**Proved** by retraining the identical configuration and asking again:

```
baseline   incumbent: lift 1.34x

GATE FAIL
  - lift 1.34 does not clear the best baseline (incumbent, 1.34) by the required 0.05;
    it needs 1.39
```

A retrain that changes nothing is refused. Before this, it would have been promoted.

## 3. The recorded commit must be the code that trained the model

`git rev-parse HEAD` answers just as confidently on a dirty tree, so the lineage could name
a commit whose code is not what ran. Populated, plausible and wrong — harder to spot than
Lab 2's `git_commit: "unknown"`, because it looks like a real answer.

```
GATE FAIL
  - the working tree has uncommitted changes, so 'git_commit' would name a commit
    that is not the code this model was trained by. Commit first.
```

## Two files, and why neither is enough alone

| File | Answers |
|---|---|
| `bank-gate-decision.json` | what the **most recent** decision was, and why |
| `approved-model.json` | which bytes are **currently allowed to serve** |

The decision file records the latest run, which is often a refusal. Read alone, a refusal
looks like "nothing is deployed", when it usually means "the model already serving was not
replaced". So the decision file also carries `serving_after_this_decision`, written after
the promotion rather than before it, and the script prints *Still serving: version N* on a
refusal.

## What is still missing

The approval record is a file in the repository, so it is only as trustworthy as the
repository. In a real system it would be signed, or the registry would be the authority and
the job would query it. The check as written catches an accident — a stale image, a wrong
build, a file copied over — and would not stop someone who could edit both files.
