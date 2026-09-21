"""The evaluation gate: what a model must clear before it may be registered.

The gate exists because "the model scored well" is not a decision. Somebody has to say what
well means, in advance, in a number, and then be held to it when the answer is inconvenient.

**What the gate measures was wrong once, and that is the more useful half of this file.**
The first version compared the candidate against baselines ranked across the whole test
period at once. Measured that way the model reached 1.34x and ranking by `euribor3m` alone
reached 1.80x, so the gate refused. The refusal was correct arithmetic on the wrong
question: the deployed job ranks one export, never the whole period, and euribor barely
moves inside one export. Ranked the way the job actually runs, the same column falls to
0.96x. The gate was rejecting the model for failing to beat a baseline the deployment
cannot use. It now measures within contact months. Working:
reports/bank-export-evaluation.md.

The thresholds are measured rather than chosen:

*Beat the best baseline by 0.05 lift.* Training the same configuration under five seeds
gives a within-month lift standard deviation of 0.0244, so two standard deviations is
0.049. A margin of 0.05 sits just above that, which means a model clearing it has improved
on the baseline rather than drawn a luckier random number.

*Beat random.* Lift below 1.0 means the ranking is worse than calling people in no
particular order, which is a state a deployed ranker should never reach.

*Beat random in every month, not only on average.* A mean of 1.4 built from one month at
2.1 and three at 0.8 is three months of call-centre time spent worse than guessing. The
mean is what the model is worth over a year; the worst month is what it is worth on a bad
one.

The gate returns a decision rather than raising, so the caller chooses what to do with a
refusal. CI fails the build; a human running it locally gets an explanation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.bank.evaluate import RankingScore

# Measured across five seeds on the held-out period, within month: sd 0.0244 lift, so two
# standard deviations is 0.049. 0.05 clears that, and is a number a person can hold.
MINIMUM_LIFT_MARGIN = 0.05

# A ranking that does not beat calling at random has no reason to exist.
MINIMUM_ABSOLUTE_LIFT = 1.0

# The floor any single month must clear. Below 1.0 the model sent the call centre after the
# wrong customers for a month, and a good annual average does not give that month back.
MINIMUM_WORST_MONTH_LIFT = 1.0

# The fields a registered model must carry to answer "where did this come from".
REQUIRED_LINEAGE_FIELDS = (
    "git_commit",
    "data_sha256",
    "data_version",
    "seed",
    "feature_names_hash",
    "train_rows",
    "metric_lift",
    "trained_at_utc",
)


@dataclass
class GateDecision:
    """Whether a candidate may be registered, and why."""

    passed: bool
    reasons: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Render the decision for a log or CI output."""
        verdict = "PASS" if self.passed else "FAIL"
        if not self.reasons:
            return f"GATE {verdict}"
        return f"GATE {verdict}\n" + "\n".join(f"  - {reason}" for reason in self.reasons)


def check_beats_baselines(candidate: RankingScore,
                          baselines: dict[str, RankingScore]) -> list[str]:
    """Return a refusal reason if the candidate does not clear the best baseline."""
    if not baselines:
        return ["no baseline was measured, so there is nothing to have improved on"]

    best_name, best_score = max(baselines.items(), key=lambda item: item[1].lift)
    required = best_score.lift + MINIMUM_LIFT_MARGIN

    if candidate.lift < required:
        return [
            f"lift {candidate.lift:.2f} does not clear the best baseline "
            f"({best_name}, {best_score.lift:.2f}) by the required "
            f"{MINIMUM_LIFT_MARGIN:.2f}; it needs {required:.2f}"
        ]
    return []


def check_beats_random(candidate: RankingScore) -> list[str]:
    """Return a refusal reason if the ranking is no better than calling at random."""
    if candidate.lift < MINIMUM_ABSOLUTE_LIFT:
        return [
            f"lift {candidate.lift:.2f} is below {MINIMUM_ABSOLUTE_LIFT:.2f}, so the "
            f"ranking is worse than calling customers in no particular order"
        ]
    return []


def check_no_month_is_worse_than_random(candidate) -> list[str]:
    """Return a refusal reason if any single month ranked worse than calling at random.

    Only applies to a within-month score. A whole-period score has no months to check, and
    is passed through rather than silently treated as having passed a check it never took.
    """
    month_lifts = getattr(candidate, "month_lifts", None)
    if not month_lifts:
        return []

    weakest_lift = min(month_lifts)
    if weakest_lift < MINIMUM_WORST_MONTH_LIFT:
        month_labels = getattr(candidate, "month_labels", [])
        weakest_position = month_lifts.index(weakest_lift)
        weakest_label = (month_labels[weakest_position]
                         if weakest_position < len(month_labels) else "unknown")
        return [
            f"month {weakest_label!r} ranked at {weakest_lift:.2f} lift, below "
            f"{MINIMUM_WORST_MONTH_LIFT:.2f}: that month's call list was worse than "
            f"calling customers in no particular order"
        ]
    return []


def check_lineage_is_complete(lineage: dict) -> list[str]:
    """Return a refusal reason for every lineage field that is missing or empty.

    An empty field counts as missing. In Lab 2 `git_commit` registered as the literal
    string "unknown" because the container had no .git directory, and the registration
    succeeded anyway — the one field whose whole job is to answer "which code made this"
    answered nothing, and nothing objected.
    """
    reasons = []
    for field_name in REQUIRED_LINEAGE_FIELDS:
        value = lineage.get(field_name)
        if value is None or value == "" or value == "unknown":
            reasons.append(f"lineage field {field_name!r} is missing or unknown")
    return reasons


def evaluate_candidate(candidate: RankingScore,
                       baselines: dict[str, RankingScore],
                       lineage: dict) -> GateDecision:
    """Decide whether this model may be registered.

    Every check runs even after one fails, so a candidate that is both weak and missing
    lineage is told both things at once rather than across two attempts.
    """
    reasons: list[str] = []
    reasons += check_beats_random(candidate)
    reasons += check_beats_baselines(candidate, baselines)
    reasons += check_no_month_is_worse_than_random(candidate)
    reasons += check_lineage_is_complete(lineage)

    return GateDecision(passed=not reasons, reasons=reasons)
