"""Shared access to the OpenAQ v3 API.

Every script that talks to OpenAQ goes through here, so the API key is read in one place,
the rate limit is respected in one place, and a failure is reported the same way everywhere.

The key is read from the environment, never from a command line argument. An argument shows
up in shell history and in the process list where anyone on the machine can read it; the
capstone brief makes a committed credential an automatic deduction, and a leaked one is the
same mistake one step earlier.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

API_ROOT = "https://api.openaq.org/v3"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

# OpenAQ's published limit for a free key is 60 requests per minute. We pause slightly
# longer than the arithmetic requires, because a 429 costs more time than the pause saves.
SECONDS_BETWEEN_REQUESTS = 1.1


def load_api_key() -> str:
    """Return the OpenAQ API key, explaining how to get one if it is missing."""
    key = os.environ.get("OPENAQ_API_KEY", "").strip()

    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("OPENAQ_API_KEY="):
                key = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                break

    if not key or key == "paste-your-key-here":
        raise SystemExit(
            "No OpenAQ API key found.\n\n"
            "  1. Register for a free key at https://explore.openaq.org/register\n"
            "  2. cp .env.example .env\n"
            "  3. Put the key in .env as OPENAQ_API_KEY=...\n\n"
            ".env is already in .gitignore, so the key cannot reach the repository."
        )
    return key


class OpenAQClient:
    """A thin, polite client for the handful of OpenAQ endpoints this project uses."""

    def __init__(self, api_key: str | None = None) -> None:
        """Prepare a session that carries the API key on every request."""
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": api_key or load_api_key(),
            "Accept": "application/json",
        })
        self.last_request_at = 0.0

    def _wait_for_rate_limit(self) -> None:
        """Sleep just long enough that we stay under the published request rate."""
        elapsed = time.monotonic() - self.last_request_at
        remaining = SECONDS_BETWEEN_REQUESTS - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_at = time.monotonic()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one endpoint and return the decoded body.

        A 429 means we were too fast, and the only correct response is to wait and retry.
        Anything else is reported with the server's own message attached, because OpenAQ
        explains its refusals clearly and hiding that behind "request failed" would throw
        away the useful half of the error.
        """
        url = f"{API_ROOT}/{path.lstrip('/')}"

        for attempt in range(1, 5):
            self._wait_for_rate_limit()
            response = self.session.get(url, params=params, timeout=60)

            if response.status_code == 429:
                backoff_seconds = 5 * attempt
                print(f"  rate limited, waiting {backoff_seconds}s", flush=True)
                time.sleep(backoff_seconds)
                continue

            if response.status_code == 401:
                raise SystemExit(
                    "OpenAQ rejected the API key (401). Check the value in .env — a key "
                    "copied with a trailing space fails exactly like a wrong one."
                )

            if not response.ok:
                raise SystemExit(
                    f"OpenAQ returned {response.status_code} for {url}\n"
                    f"  params: {params}\n"
                    f"  body:   {response.text[:400]}"
                )

            return response.json()

        raise SystemExit(f"still rate limited after 4 attempts on {url}")

    def get_all_pages(self, path: str, params: dict[str, Any],
                      page_limit: int = 100) -> list[dict[str, Any]]:
        """Follow pagination until the API stops returning results.

        `page_limit` is a stop, not a target. Without one, a wrong filter that matches
        everything turns a small query into thousands of requests before anyone notices.
        """
        collected: list[dict[str, Any]] = []
        page = 1

        while page <= page_limit:
            paged_params = dict(params)
            paged_params["page"] = page
            body = self.get(path, paged_params)
            results = body.get("results", [])
            collected.extend(results)

            found = body.get("meta", {}).get("found")
            limit = body.get("meta", {}).get("limit", len(results))
            if not results or len(results) < limit:
                break
            if isinstance(found, int) and len(collected) >= found:
                break
            page += 1

        return collected
