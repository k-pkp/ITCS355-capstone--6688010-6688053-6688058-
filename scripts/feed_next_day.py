"""Advance the replay by one day: publish the next slice of the campaign as tonight's export.

    python scripts/feed_next_day.py --dry-run
    python scripts/feed_next_day.py

The dataset is a finished campaign from 2008-2010, not a live feed. Without this step the
nightly job reads the same file every night, publishes the same call list, and demonstrates
nothing that a single run would not: the freshness gate never has a fresh input to pass, the
drift numbers never move, and "it runs every night" means "it runs the same night, nightly".

So the campaign is **replayed**. A cursor in the bucket records how far through the held-out
period the replay has reached. Each run takes the next slice, in campaign order, and writes
it as the incoming export. The rows are real rows that real people were really called about;
what is synthetic is only the calendar.

Two properties this buys, and the second is not available to a live system:

**The freshness gate becomes real.** The export is written by a separate scheduled job. If
that job fails, nothing rewrites the file, it ages past 24 hours, and the scorer refuses. The
failure being demonstrated is the one that actually happens in production — an upstream
export that did not arrive — rather than a file whose timestamp was edited to prove a point.

**The outcomes are already known.** Every replayed row carries the answer the customer gave.
A live campaign waits weeks to find out whether a call list was any good; this one can
measure the realised lift of last night's list this morning. Historical data is worse than
live data in every way except this one, and this is the way that matters for demonstrating
a monitoring loop that closes.

The replay draws only from the period the model never trained on. Replaying rows the model
was fitted to would produce a system that looks better every night for the worst reason.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bank import cloud, splits

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "data" / "bank" / "bank-additional-full.csv"

# Where the replay keeps its place. In the bucket rather than in the container, because the
# container is new every night and a cursor that resets every night is not a cursor.
CURSOR_OBJECT = "capstone/state/replay-cursor.json"
INCOMING_OBJECT = "capstone/incoming/contacts.csv"

# The rows the replay walks through, kept in the bucket rather than in the image. The
# course's first rule is that data does not go in Git, and the same reasoning applies to a
# container layer: an image that carries its dataset is rebuilt every time the data changes
# and cannot be pointed at a different one.
SOURCE_OBJECT = "capstone/replay/source.csv"

# One night's export. The real campaign called about 500 people a day from an export of
# roughly 3,000; the replay is compressed so that a demonstration can watch a fortnight of
# operation rather than a fortnight. The call budget is set as a share of the export by the
# scoring job, so the compression does not change what fraction of the list gets called.
ROWS_PER_NIGHT = 600


def parse_command_line() -> argparse.Namespace:
    """Command line for the replay feeder."""
    parser = argparse.ArgumentParser(
        description="Publish the next day of the replayed campaign")
    parser.add_argument("--dataset", type=Path, default=DATASET,
                        help="the full campaign, read locally. Used to publish the replay "
                             "source; the scheduled run reads the source from the bucket.")
    parser.add_argument("--publish-source", action="store_true",
                        help="upload the held-out period to the bucket as the replay "
                             "source, then stop. Run once, from a machine that has the "
                             "dataset.")
    parser.add_argument("--rows", type=int, default=ROWS_PER_NIGHT)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be published without writing anything")
    parser.add_argument("--reset", action="store_true",
                        help="start the replay again from the beginning of the held-out "
                             "period")
    return parser.parse_args()


def publish_replay_source(dataset_path: Path) -> int:
    """Upload the held-out period to the bucket, once, as the rows the replay walks.

    Only the held-out period. Replaying rows the model was fitted to would produce a system
    that scores better every night for the worst possible reason, and nothing in the running
    system could tell the difference.
    """
    if not dataset_path.exists():
        raise SystemExit(f"{dataset_path} not found; run `dvc pull`")

    dataset = pd.read_csv(dataset_path, sep=";")
    held_out = splits.split_by_time(dataset).test

    local_copy = Path("/tmp/replay-source.csv")
    held_out.to_csv(local_copy, sep=";", index=False)
    published_uri = cloud.upload(local_copy, SOURCE_OBJECT)

    print(f"published {len(held_out):,} held-out rows to {published_uri}")
    return 0


def read_replay_source() -> pd.DataFrame:
    """Fetch the rows the replay walks through from the bucket."""
    local_copy = Path("/tmp/replay-source.csv")
    try:
        cloud.download(SOURCE_OBJECT, local_copy)
    except FileNotFoundError:
        raise SystemExit(
            f"no replay source at gs://{cloud.BUCKET}/{SOURCE_OBJECT}. Publish it once "
            f"with: python scripts/feed_next_day.py --publish-source"
        )
    return pd.read_csv(local_copy, sep=";")


def read_cursor() -> int:
    """Return how many rows of the replay have already been published."""
    local_copy = Path("/tmp/replay-cursor.json")
    try:
        cloud.download(CURSOR_OBJECT, local_copy)
    except FileNotFoundError:
        return 0

    return int(json.loads(local_copy.read_text())["rows_published"])


def write_cursor(rows_published: int, exhausted: bool) -> None:
    """Record how far the replay has reached."""
    local_copy = Path("/tmp/replay-cursor.json")
    local_copy.write_text(json.dumps({
        "rows_published": rows_published,
        "exhausted": exhausted,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")
    cloud.upload(local_copy, CURSOR_OBJECT)


def main() -> int:
    """Publish the next slice of the replay, or stop when the campaign runs out."""
    options = parse_command_line()

    if options.publish_source:
        return publish_replay_source(options.dataset)

    replay_source = read_replay_source()
    print(f"replay source: the held-out period, {len(replay_source):,} rows the model "
          f"never trained on")

    already_published = 0 if options.reset else read_cursor()
    remaining = len(replay_source) - already_published

    if remaining <= 0:
        # Deliberately not looping back to the start. The replay ending means no new export
        # arrives, the file ages, and the scoring job refuses on staleness -- which is the
        # correct behaviour for an upstream that has stopped sending, and is more useful to
        # demonstrate than an endless loop that can never show it.
        print("the replay is exhausted: no export was published.")
        print("The scoring job will refuse on staleness within 24 hours, which is what "
              "should happen when an upstream stops sending.")
        write_cursor(already_published, exhausted=True)
        return 2

    rows_tonight = min(options.rows, remaining)
    slice_to_publish = replay_source.iloc[
        already_published:already_published + rows_tonight]

    day_number = already_published // options.rows + 1
    total_days = -(-len(replay_source) // options.rows)  # ceiling division
    subscribe_rate = (slice_to_publish["y"] == "yes").mean()

    print(f"replay day {day_number} of {total_days}: rows "
          f"{already_published:,}–{already_published + rows_tonight:,}")
    print(f"  {rows_tonight:,} customers, of whom {subscribe_rate:.1%} subscribed "
          f"(the answer the model is not given)")

    if options.dry_run:
        print("\ndry run: nothing was published and the cursor was not moved")
        return 0

    local_export = Path("/tmp/contacts.csv")
    slice_to_publish.to_csv(local_export, sep=";", index=False)
    published_uri = cloud.upload(local_export, INCOMING_OBJECT)
    write_cursor(already_published + rows_tonight, exhausted=False)

    print(f"\npublished {published_uri}")
    print("The scoring job reads this file, and reads its age from the object's own "
          "metadata rather than from its own clock.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
