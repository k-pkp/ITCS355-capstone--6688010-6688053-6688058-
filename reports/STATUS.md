# ITCS355 — where everything actually stands

**20 September 2026.** Every figure below was read from the repositories and from Google
Cloud, not recalled. Tests were run, not assumed. Where something is projected rather than
measured, it says so.

| | |
|---|--:|
| Lab marks delivered | **40 / 40** |
| Tests passing | **305** |
| Capstone marks in play | **45** |
| Cloud resources billing | **0** |

"Delivered" means the work is complete and pushed, not that it has been graded.

---

## The five labs

Repository `ITCS355-lab-6688010` · 12 commits · local and remote both at `eeab528`, so
everything is pushed.

| Lab | Status | Tests | Evidence |
|---|---|--:|--:|
| 1 — Reproducibility and the container | complete | 45 | 2 screenshots |
| 2 — Tracking and model registry | complete | 45 | 3 screenshots, 1 report |
| 3 — Serving, load testing, rollback | complete | 45 | 7 evidence files, 3 reports |
| 4 — CI/CD, observability, drift | complete | 45 | 3 screenshots, 3 reports |
| 5 — Cloud, LLM ops, cost | complete | 45 | 5 screenshots, 5 reports |

**What each one actually demonstrated**

- **Lab 1.** Digest-pinned image, DVC remote, eight capability slots. The two habits that
  later saved the most: pinning by digest rather than tag, and refusing to let configuration
  live in code.
- **Lab 2.** The study ran as Vertex spot jobs; one was interrupted and resumed from its
  checkpoint. Three defects appeared that were invisible on a laptop, including `git_commit`
  registering as the literal string `unknown`.
- **Lab 3.** The real endpoint missed the p95 target by 4×, mostly network. The platform
  reported a broken deployment as healthy. The 90/10 canary could never have fired — 426
  requests cannot resolve a 0.0189 gap.
- **Lab 4.** A deliberately bad commit was blocked at the data contract step in 47 seconds.
  The drift alert fired on a real policy, and the panel was proved against a control window
  rather than only against the drifted one.
- **Lab 5.** The pipeline was submitted and run with the gate branch not taken. Live Gemini
  recording scored 13/13. Measured bill 27.83 THB, of which the endpoint was 46% for 1.45
  hours of existence.

---

## The capstone

Repository `itcs355-capstone` · 16 commits · 80 tests · all twelve design steps built.

| Criterion | Status | What exists |
|---|---|---|
| R1 Reproducible pipeline | built | 41,188 rows under DVC with SHA-256, a seven-rule contract, a time-ordered split, a lineage gate with all nine fields populated |
| R2 Deployment and CI/CD | built | Nightly batch job of six steps; CI runs lint, then tests, then calls out the leakage guard explicitly |
| R3 Monitoring and reliability | built | Drift check across seven columns, six alerting; run metrics per night; teardown check reports nothing billing |
| R4 Failure handling and defence | built | The stale-input failure demonstrated both ways on the same file — published without the gate, refused with it, neither run producing an error |
| R5 Documentation | built | README, design in English and Thai, glossary, cost report, model card stating that the model loses and that fairness was not measured |
| Proposal (M2) | **needs names** | Four pages, every figure measured from the data. Blocked only on three team names |
| Demo and defence (15 marks) | **not rehearsed** | The material exists; eight minutes plus five of questions has not been practised |

---

## One thing to fix today

**The capstone repository has no git remote.**

Sixteen commits exist only on this machine. The labs are safely pushed; the capstone is not
backed up anywhere. A disk failure or a wiped WSL distribution loses all of it.

```
git remote add origin <url> && git push -u origin main
```

Five minutes, and it removes the only real risk on this page.

---

## What was found by building rather than by reading

Each of these was silent. Nothing errored, and the output looked correct.

**A drift detector reported no drift at all.** A column whose reference and current ranges
do not overlap scored PSI 0.0000, because three distinct values collapsed the bucket edges
and both were overwritten with infinities. It now scores 9.89. A low score is exactly what a
healthy column produces, so nothing downstream could ever have caught this.

**A sensor stuck at 1,680 µg/m³ for eight days passed every freshness check.** It kept
reporting current timestamps. Freshness and plausibility turned out to be different
questions, and the design only asked one of them.

**A pipeline step reported success while writing to the wrong place.** It printed the path
it meant to write rather than the path the upload returned. Object storage accepts any
string as a name, so nothing failed.

**Teardown crashed partway through and left resources billing.** Its output read like a
broken verifier rather than an accruing bill. A cleanup routine that stops at the first
surprise is worse than none, because it also reports having tried.

**The model lost to sorting by a single column.** 1.34× against 1.80×. Nobody would have
known without measuring a baseline first, and the evaluation gate refused to register it.

---

## What is left

1. **Push the capstone somewhere.** Five minutes, and it removes the only risk of losing
   work.
2. **Fill in three names and send the proposal.** Approval is required before building, and
   the building is already done — so the sooner it goes in, the shorter the window where
   that matters.
3. **Make the model beat the baseline.** Train on a recent window rather than on all
   history. Not required for the gate to be a deliverable, but a passing model is a better
   story than a refused one.
4. **Rehearse the eight minutes.** The largest single block of unearned marks. The failure
   demonstration runs in under a minute, which is the part that will land.

---

## Honest limits on this page

Test counts, commit hashes, the gate decision and the cloud resource check were read from
the repositories and from Google Cloud at 06:10 on 20 September 2026.

The capstone's cost figures are projected from rates verified during Lab 5 and have not been
reconciled against an invoice — billing export to BigQuery is not configured on the project.

Nothing here has been graded. "Delivered" means complete and pushed.
