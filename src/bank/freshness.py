"""The freshness gate: refusing to score data that is no longer today's.

This is the control for the failure the project is built around. The overnight customer
export does not arrive. Yesterday's file is still in the bucket. The job reads it, scores
it, and publishes a call list that looks entirely normal — the same number of rows, the same
distribution of scores, no error anywhere, and a green dashboard. In the morning, agents
call the people they called yesterday.

Nothing in a normal pipeline notices, because nothing in a normal pipeline asks *when* the
data is from. It asks whether the read succeeded, and the read succeeded.

So the gate asks the only question that catches it: how old is this input? And when the
answer is too old it **publishes nothing**. That choice is the argument of the whole design.
A missing call list is an obvious problem somebody fixes in ten minutes. A plausible wrong
one is worked through for a day, and nobody discovers it until a customer complains about
being called twice.

The threshold is the freshness requirement stated in the proposal: 24 hours, because the
list is consumed once a day and a two-day-old list ranks customers who were already called.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# From the proposal's freshness table: the list is used daily, so an input older than a day
# is describing a day that has already been worked through.
MAXIMUM_INPUT_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class FreshnessDecision:
    """Whether an input may be scored, with the age that decided it."""

    fresh: bool
    age: timedelta
    source_modified_at: datetime
    checked_at: datetime

    @property
    def age_hours(self) -> float:
        """The input's age in hours, for logging and for metrics."""
        return self.age.total_seconds() / 3600

    def __str__(self) -> str:
        """Render the decision for a log or for the job's output."""
        verdict = "FRESH" if self.fresh else "STALE"
        return (f"{verdict}: input is {self.age_hours:.1f}h old "
                f"(modified {self.source_modified_at:%Y-%m-%d %H:%M}Z, "
                f"limit {MAXIMUM_INPUT_AGE.total_seconds() / 3600:.0f}h)")


class StaleInputError(RuntimeError):
    """Raised when the job is asked to score an input that is too old.

    A distinct exception type rather than a bare RuntimeError, so the nightly job can catch
    exactly this and alert on it, while a genuine crash still propagates as a crash. The two
    need different responses: this one is an upstream problem, and the other is ours.
    """


def source_modified_at(path: Path) -> datetime:
    """Return when the input was last written, as an aware UTC timestamp.

    Read from the file's own metadata rather than from the filename or from the time the
    job happens to run. A job that trusts its own clock to decide what day the data is from
    will believe whatever it is handed.
    """
    modified_seconds = path.stat().st_mtime
    return datetime.fromtimestamp(modified_seconds, tz=timezone.utc)


def check(path: Path, now: datetime | None = None,
          maximum_age: timedelta = MAXIMUM_INPUT_AGE) -> FreshnessDecision:
    """Decide whether this input is recent enough to score.

    `now` is injectable so that the tests can age a file without waiting a day, and so the
    job can be replayed against a known moment when reconstructing an incident.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    checked_at = now or datetime.now(timezone.utc)
    modified_at = source_modified_at(path)
    age = checked_at - modified_at

    return FreshnessDecision(
        fresh=age <= maximum_age,
        age=age,
        source_modified_at=modified_at,
        checked_at=checked_at,
    )


def require_fresh(path: Path, now: datetime | None = None,
                  maximum_age: timedelta = MAXIMUM_INPUT_AGE) -> FreshnessDecision:
    """Return the decision if the input is fresh, and raise if it is not.

    The raising version exists so the nightly job cannot continue past a stale input by
    forgetting to read a boolean. A gate that has to be remembered is not a gate.
    """
    decision = check(path, now=now, maximum_age=maximum_age)
    if not decision.fresh:
        raise StaleInputError(
            f"refusing to publish a call list from an input {decision.age_hours:.1f}h "
            f"old (limit {maximum_age.total_seconds() / 3600:.0f}h). "
            f"Publishing nothing is deliberate: a missing list is noticed in minutes, "
            f"and a plausible wrong one is worked through for a day."
        )
    return decision
