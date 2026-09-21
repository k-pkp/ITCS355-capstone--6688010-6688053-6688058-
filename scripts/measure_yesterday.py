"""Score last night's call list against what the customers actually said.

    python scripts/measure_yesterday.py --date 2026-09-21

A live campaign cannot do this. It publishes a list, the agents work it, and the outcomes
arrive over the following weeks — so the question "was last night's list any good?" has no
answer until long after it stops being useful. Lab 3 ran into the same wall: the label there
arrives seven days late, which is why the canary had to be judged on a label-free proxy that
turned out to be too weak to see anything.

The replay has the answers already, because the campaign finished in 2010. That is the one
respect in which historical data beats live data, and it is the one that matters for showing
a monitoring loop that closes: the realised lift of a published list can be measured the next
morning and put on the same dashboard as the inputs.

**The model never sees this column.** `features.EXCLUDED_COLUMNS` drops the target before
anything is scored, and that exclusion is what makes the measurement honest rather than
circular.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bank import cloud, contract

INCOMING_OBJECT = "capstone/incoming/contacts.csv"
CALL_LIST_PREFIX = "capstone/call-lists"


def parse_command_line() -> argparse.Namespace:
    """Command line for the realised-lift measurement."""
    parser = argparse.ArgumentParser(
        description="Measure a published call list against the known outcomes")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="which published call list to measure, YYYY-MM-DD")
    parser.add_argument("--emit-metrics", action="store_true",
                        help="send the realised lift to Cloud Monitoring")
    return parser.parse_args()


def main() -> int:
    """Compare who was called against who subscribed."""
    options = parse_command_line()

    export_path = Path("/tmp/measured-export.csv")
    call_list_path = Path("/tmp/measured-call-list.csv")

    try:
        cloud.download(INCOMING_OBJECT, export_path)
        cloud.download(f"{CALL_LIST_PREFIX}/call-list-{options.date}.csv", call_list_path)
    except FileNotFoundError as missing:
        print(f"nothing to measure: {missing}")
        return 1

    export = pd.read_csv(export_path, sep=";")
    call_list = pd.read_csv(call_list_path)

    if contract.TARGET_COLUMN not in export.columns:
        print(f"the export carries no {contract.TARGET_COLUMN!r} column, so there is "
              f"nothing to measure against")
        return 1

    export_subscribed = (export[contract.TARGET_COLUMN] == "yes").sum()
    called_subscribed = (call_list[contract.TARGET_COLUMN] == "yes").sum()

    export_rate = export_subscribed / len(export)
    called_rate = called_subscribed / len(call_list)
    realised_lift = called_rate / export_rate if export_rate else float("nan")

    # What the same number of calls would have found at random, which is the comparison the
    # supervisor actually faces: they are going to make the calls either way.
    subscriptions_at_random = export_rate * len(call_list)
    subscriptions_gained = called_subscribed - subscriptions_at_random

    print(f"call list for {options.date}")
    print(f"  export:  {len(export):,} customers, {export_subscribed} subscribed "
          f"({export_rate:.1%})")
    print(f"  called:  {len(call_list):,} customers, {called_subscribed} subscribed "
          f"({called_rate:.1%})")
    print(f"  realised lift: {realised_lift:.2f}x")
    print(f"  {subscriptions_gained:+.1f} subscriptions against calling the same "
          f"{len(call_list)} people at random")

    if options.emit_metrics:
        cloud.emit_metrics({
            "realised_lift": realised_lift,
            "realised_hit_rate": called_rate,
            "subscriptions_gained": subscriptions_gained,
        })
        print(f"\nemitted at {datetime.now(timezone.utc).isoformat()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
