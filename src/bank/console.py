"""Make the scripts print the same bytes on every machine.

Python picks an encoding for stdout from the environment. Here that is UTF-8; on
Windows a redirected stream gets the system code page instead, and the reports and
headings in this project are full of em dashes, middots and times signs. The result is
that `python scripts/train_bank.py` prints fine to a Windows console and raises
UnicodeEncodeError the moment the same command is redirected to a file -- which is what
a teammate hit, and what made a one-line patch look like the fix.

Every script calls this first, so the difference between the two machines disappears
instead of being worked around one line at a time.
"""
from __future__ import annotations

import sys


def use_utf8_for_output() -> None:
    """Switch stdout and stderr to UTF-8, whatever the environment chose."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            # Already wrapped, or not a real stream -- a captured pipe in a test, say.
            # Nothing to reconfigure, and nothing that needs to fail here.
            pass
