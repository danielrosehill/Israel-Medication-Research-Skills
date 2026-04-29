#!/usr/bin/env python3
"""Israeli Drug Registry (israeldrugs.health.gov.il) lookup.

  search <query>          POST /GovServiceList/IDRServer/SearchByName
  fetch  <dragRegNum>     POST /GovServiceList/IDRServer/GetSpecificDrug

If the endpoint returns a non-JSON response, exit non-zero. The caller
should treat that as a transient failure (try later, or read the site
in a browser); do not retry in a loop.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

BASE = "https://israeldrugs.health.gov.il"
SEARCH_URL = f"{BASE}/GovServiceList/IDRServer/SearchByName"
FETCH_URL = f"{BASE}/GovServiceList/IDRServer/GetSpecificDrug"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "User-Agent": UA,
}


def _post(url: str, body: dict[str, Any]) -> Any:
    try:
        r = requests.post(url, json=body, headers=HEADERS, timeout=25)
    except requests.RequestException as e:
        sys.stderr.write(f"Network error: {e}\n")
        sys.exit(2)

    if r.status_code == 502 and "DataDashboard-maintanance" in r.text:
        sys.stderr.write("Israeli Drug Registry is in maintenance mode. Try again later.\n")
        sys.exit(3)

    if "application/json" not in r.headers.get("Content-Type", ""):
        sys.stderr.write(
            f"Lookup failed (HTTP {r.status_code}, non-JSON response). "
            "Try again later or have the user load the site in a browser.\n"
        )
        sys.exit(4)

    try:
        return r.json()
    except ValueError:
        sys.stderr.write("Lookup failed: response was not valid JSON.\n")
        sys.exit(5)


def cmd_search(args: argparse.Namespace) -> None:
    body = {
        "val": args.query,
        "prescription": False,
        "healthServices": False,
        "pageIndex": 1,
        "orderBy": 0,
    }
    print(json.dumps(_post(SEARCH_URL, body), ensure_ascii=False, indent=2))


def cmd_fetch(args: argparse.Namespace) -> None:
    print(json.dumps(_post(FETCH_URL, {"dragRegNum": args.reg_num}), ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="op", required=True)

    s = sub.add_parser("search", help="search by name / active ingredient")
    s.add_argument("query")
    s.set_defaults(func=cmd_search)

    f = sub.add_parser("fetch", help="fetch full record by registration number")
    f.add_argument("reg_num")
    f.set_defaults(func=cmd_fetch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
