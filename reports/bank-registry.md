# Model registry — `bank-call-list-ranker`

Written by `scripts/describe_registry.py` from the registry itself, so that the claim can be checked rather than taken on trust.

## Version 1

| Lineage field | Value |
|---|---|
| `call_budget` | `500` |
| `data_sha256` | `74adfc578bf77a7ff4bb1ba4a9f8709d9e3c6907342959c2c8416847e0afb4d8` |
| `data_version` | `f6cb2c1256ffe2836b36df321f46e92c` |
| `feature_names_hash` | `589bc39141290576` |
| `git_commit` | `695ef100c50fac4bbad9530368cabb17d0a73737` |
| `metric` | `within-month lift at the supervisor's call share` |
| `metric_lift` | `1.3396` |
| `seed` | `20260101` |
| `train_rows` | `4000` |
| `trained_at_utc` | `2026-09-21T01:53:14.694650+00:00` |
| `worst_month_lift` | `1.2518` |

## What each field is for

| Field | Answers |
|---|---|
| `git_commit` | which code produced this |
| `data_sha256` | whether a file is byte-identical to the one trained on |
| `data_version` | which versioned copy to `dvc pull` to get those bytes back |
| `seed` | what to set to reproduce the fit |
| `feature_names_hash` | whether the serving code builds the same columns |
| `train_rows` | how much history the model saw |
| `metric_lift` / `metric` | what it scored, and on which measurement |
| `worst_month_lift` | what it scored on its weakest month |
| `trained_at_utc` | when |

The gate refuses any registration where one of these is missing or reads `unknown`, which is what Lab 2 shipped without noticing.
