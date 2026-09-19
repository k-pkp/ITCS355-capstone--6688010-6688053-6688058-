# Drift report

Reference: the training window, 24,712 rows. Current: the held-out final period, 8,239 rows.

| Column | PSI | Verdict |
|---|--:|---|
| `euribor3m` | 25.4203 | **ALERT** |
| `emp.var.rate` | 16.2162 | **ALERT** |
| `nr.employed` | 9.8911 | **ALERT** |
| `cons.price.idx` | 3.7381 | **ALERT** |
| `cons.conf.idx` | 3.6583 | **ALERT** |
| `age` | 0.9122 | **ALERT** |
| `campaign` | 0.0624 | stable |

Threshold 0.2, carried over from Lab 4 where it was set by measuring an unchanged window against the reference.

## What this is detecting

The campaign ran May 2008 to November 2010, through the financial crisis. The macroeconomic columns are not noise here: they record the conditions the calls were made in, and those conditions changed completely. The subscription rate moves from 4.8% in the training window to 30.8% in the current one.

**This run is expected to alert.** A drift check that found nothing here would mean the detector was broken, not that the world was calm.

## The limit of this measure

PSI measures how far the input moved, not how much the model minds. Measured in Lab 4 on the same detector: a shift scoring 0.383 cost 0.0100 ROC AUC, while one scoring 0.2627 cost 0.0167 — the larger PSI did the smaller damage. So a PSI alert opens an investigation and does not rank incidents.
