"""Prove the gate refuses what it should, and admits what it should.

Both halves matter. A gate that refuses everything blocks the project and gets removed; a
gate that admits everything is decoration. The tests below pin the boundary from each side,
including the case that is exactly at the margin, because that is the one a later "small
tidy-up" of the comparison operator would move.
"""
from __future__ import annotations

from src.bank import gate
from src.bank.evaluate import RankingScore


def make_score(lift: float) -> RankingScore:
    """Build a ranking score with the given lift, for testing the gate alone."""
    call_budget = 500
    baseline_hits = 100.0
    hits = int(round(lift * baseline_hits))
    return RankingScore(
        call_budget=call_budget,
        hits=hits,
        hit_rate=hits / call_budget,
        baseline_hits=baseline_hits,
        lift=lift,
    )


def complete_lineage() -> dict:
    """A lineage dictionary with every required field populated."""
    return {
        "git_commit": "0123456789abcdef0123456789abcdef01234567",
        "data_sha256": "74adfc578bf77a7ff4bb1ba4a9f8709d9e3c6907342959c2c8416847e0afb4d8",
        "data_version": "f6cb2c1256ffe2836b36df321f46e92c",
        "seed": 20260101,
        "feature_names_hash": "abc123def4567890",
        "train_rows": 24712,
        "metric_lift": 2.5,
        "trained_at_utc": "2026-09-20T05:00:00+00:00",
    }


def test_a_clearly_better_model_passes() -> None:
    """The gate must let a genuine improvement through."""
    decision = gate.evaluate_candidate(
        make_score(2.50), {"euribor3m": make_score(1.80)}, complete_lineage())
    assert decision.passed, decision.reasons


def test_a_model_that_loses_to_a_baseline_is_refused() -> None:
    """This is the real case: our first model scores 1.34 against a 1.80 baseline."""
    decision = gate.evaluate_candidate(
        make_score(1.34), {"euribor3m": make_score(1.80)}, complete_lineage())
    assert not decision.passed
    assert any("does not clear the best baseline" in reason for reason in decision.reasons)


def test_a_model_that_only_ties_the_baseline_is_refused() -> None:
    """Equal is not better. Deploying a tie spends effort and changes nothing."""
    decision = gate.evaluate_candidate(
        make_score(1.80), {"euribor3m": make_score(1.80)}, complete_lineage())
    assert not decision.passed


def test_a_model_inside_the_seed_noise_is_refused() -> None:
    """An improvement smaller than the margin is a luckier random seed.

    Measured across five seeds: sd 0.0152 lift. A 0.03 improvement is inside two standard
    deviations and must not count as progress.
    """
    decision = gate.evaluate_candidate(
        make_score(1.83), {"euribor3m": make_score(1.80)}, complete_lineage())
    assert not decision.passed


def test_a_model_exactly_at_the_margin_passes() -> None:
    """The boundary is inclusive, and pinning it stops it drifting in a refactor."""
    baseline_lift = 1.80
    decision = gate.evaluate_candidate(
        make_score(baseline_lift + gate.MINIMUM_LIFT_MARGIN),
        {"euribor3m": make_score(baseline_lift)},
        complete_lineage(),
    )
    assert decision.passed, decision.reasons


def test_a_ranking_worse_than_random_is_refused() -> None:
    """Lift below 1.0 means the list is worse than calling people in any order."""
    decision = gate.evaluate_candidate(
        make_score(0.80), {"file_order": make_score(0.21)}, complete_lineage())
    assert not decision.passed
    assert any("worse than calling customers" in reason for reason in decision.reasons)


def test_missing_lineage_is_refused_even_when_the_model_is_good() -> None:
    """A strong model with no provenance is still not registerable."""
    lineage = complete_lineage()
    del lineage["data_version"]

    decision = gate.evaluate_candidate(
        make_score(2.50), {"euribor3m": make_score(1.80)}, lineage)
    assert not decision.passed
    assert any("data_version" in reason for reason in decision.reasons)


def test_the_word_unknown_counts_as_missing() -> None:
    """In Lab 2 git_commit registered as the literal string 'unknown' and was accepted.

    A field containing a plausible-looking placeholder is worse than an empty one,
    because it reads as populated in every report that lists it.
    """
    lineage = complete_lineage()
    lineage["git_commit"] = "unknown"

    decision = gate.evaluate_candidate(
        make_score(2.50), {"euribor3m": make_score(1.80)}, lineage)
    assert not decision.passed
    assert any("git_commit" in reason for reason in decision.reasons)


def test_having_no_baseline_at_all_is_refused() -> None:
    """Without a baseline there is nothing to have improved on, so nothing is proven."""
    decision = gate.evaluate_candidate(make_score(5.0), {}, complete_lineage())
    assert not decision.passed


def test_every_failing_reason_is_reported_at_once() -> None:
    """A weak model with broken lineage should be told both things in one run."""
    lineage = complete_lineage()
    lineage["seed"] = None

    decision = gate.evaluate_candidate(
        make_score(0.5), {"euribor3m": make_score(1.80)}, lineage)

    assert not decision.passed
    assert len(decision.reasons) >= 3, decision.reasons
