"""Guard the freshness gate, which is the control the whole project is built around.

The gate's job is to notice something no other check can see. A stale file passes the data
contract, produces a normal row count, yields a normal score distribution and raises no
error. The only thing wrong with it is *when* it is from.

So these tests age a file rather than corrupt it: every one of them uses input that is
perfectly valid and simply old.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.bank import freshness


def write_file_aged(directory: Path, hours_old: float) -> Path:
    """Write a small file and backdate its modification time.

    Backdating rather than waiting: a test that needed a real 25 hours to pass would never
    be run, and a gate whose test is never run is not guarded.
    """
    path = directory / "contacts.csv"
    path.write_text("age;job\n35;technician\n")

    modified_at = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    timestamp = modified_at.timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def test_a_file_written_now_is_fresh(tmp_path: Path) -> None:
    """The ordinary case must pass, or the gate blocks every healthy night."""
    path = write_file_aged(tmp_path, hours_old=0)
    assert freshness.check(path).fresh


def test_a_file_from_this_morning_is_fresh(tmp_path: Path) -> None:
    """An input a few hours old is normal: the export runs before the job does."""
    path = write_file_aged(tmp_path, hours_old=6)
    decision = freshness.check(path)
    assert decision.fresh
    assert 5.9 < decision.age_hours < 6.1


def test_a_file_from_yesterday_is_stale(tmp_path: Path) -> None:
    """This is the failure: yesterday's export, still sitting in the bucket."""
    path = write_file_aged(tmp_path, hours_old=25)
    decision = freshness.check(path)
    assert not decision.fresh
    assert decision.age_hours > 24


def test_the_boundary_is_pinned(tmp_path: Path) -> None:
    """Exactly at the limit is still fresh; a minute past it is not.

    Pinned from both sides because a later change from <= to < would move the boundary
    silently, and nothing else in the system would report it.
    """
    just_inside = write_file_aged(tmp_path, hours_old=23.99)
    assert freshness.check(just_inside).fresh

    just_outside = write_file_aged(tmp_path, hours_old=24.02)
    assert not freshness.check(just_outside).fresh


def test_require_fresh_raises_on_a_stale_input(tmp_path: Path) -> None:
    """The raising form exists so the job cannot continue by forgetting to read a flag."""
    path = write_file_aged(tmp_path, hours_old=48)
    with pytest.raises(freshness.StaleInputError, match="refusing to publish"):
        freshness.require_fresh(path)


def test_require_fresh_returns_the_decision_when_input_is_good(tmp_path: Path) -> None:
    """On a healthy night it must hand back the decision rather than raising."""
    path = write_file_aged(tmp_path, hours_old=2)
    decision = freshness.require_fresh(path)
    assert decision.fresh


def test_the_stale_error_is_its_own_type(tmp_path: Path) -> None:
    """A stale input and a crash need different responses, so they need different types.

    The job catches this one and alerts on it as an upstream problem. Anything else
    propagates as a genuine failure of ours.
    """
    path = write_file_aged(tmp_path, hours_old=30)
    with pytest.raises(freshness.StaleInputError):
        freshness.require_fresh(path)
    assert issubclass(freshness.StaleInputError, RuntimeError)


def test_a_missing_input_is_not_silently_fresh(tmp_path: Path) -> None:
    """A file that does not exist must raise, never return a decision.

    Returning "fresh" for a missing file would be the same failure class the gate exists
    to prevent, reached from the other direction.
    """
    with pytest.raises(FileNotFoundError):
        freshness.check(tmp_path / "nothing-here.csv")


def test_the_clock_can_be_injected_for_replay(tmp_path: Path) -> None:
    """Reconstructing an incident means asking what the gate saw at the time."""
    path = write_file_aged(tmp_path, hours_old=0)
    modified_at = freshness.source_modified_at(path)

    assert freshness.check(path, now=modified_at + timedelta(hours=1)).fresh
    assert not freshness.check(path, now=modified_at + timedelta(hours=30)).fresh


def test_the_decision_reads_clearly_in_a_log(tmp_path: Path) -> None:
    """The job prints this line every night, so it has to say something useful."""
    path = write_file_aged(tmp_path, hours_old=30)
    rendered = str(freshness.check(path))
    assert "STALE" in rendered
    assert "30." in rendered
