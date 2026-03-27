#!/usr/bin/env python3
"""
history_almanac_v2.py — A terminal almanac powered by the Day in History API.

Uses the zingu-apis package — pagination, retries, and analytics handled automatically.

Usage:
    python history_almanac_v2.py              # today's history
    python history_almanac_v2.py july 4       # specific date
    python history_almanac_v2.py december 25  # another date
"""

import sys
from datetime import date

import zingu_apis

API = zingu_apis.api("dayinhistory.dev:day-in-history-api")

# Result access patterns:
#   result.data       — unwrapped content (dict if single item, list if multiple)
#   result[0]         — first item directly
#   for item in result — iterate items
#   result["analytics"] — timing, pages, bytes
#   result["errors"]  — errors (empty on success)
#   print(result)     — human-readable summary with field names
#   result.to_json()  — raw JSON string


def main():
    if len(sys.argv) == 3:
        month, day = sys.argv[1].lower(), int(sys.argv[2])
        label = f"{month.title()} {day}"
        events = API.fetch(f"/events/{month}/{day}/", max_items=10)
        births = API.fetch(f"/births/{month}/{day}/", max_items=10)
        deaths = API.fetch(f"/deaths/{month}/{day}/", max_items=10)
    else:
        label = date.today().strftime("%B %d")
        events = API.fetch("/today/events/", max_items=10)
        births = API.fetch("/today/births/", max_items=10)
        deaths = API.fetch("/today/deaths/", max_items=10)

    for result in [events, births, deaths]:
        if result["errors"]:
            print(f"Error: {result['errors']}")
            return

    print(f"\n--- This Day in History: {label} ---\n")

    print("EVENTS:")
    for e in events:
        print(f"  {e.get('year', '????')}  {e.get('title', e.get('description', ''))}")

    print("\nBORN ON THIS DAY:")
    for b in births:
        print(f"  {b.get('birth_year', '????')}  {b.get('name', '')} — {b.get('description', '')}")

    print("\nDIED ON THIS DAY:")
    for d in deaths:
        print(f"  {d.get('death_year', '????')}  {d.get('name', '')} — {d.get('description', '')}")

    total = len(events) + len(births) + len(deaths)
    total_ms = events["analytics"]["elapsed_ms"] + births["analytics"]["elapsed_ms"] + deaths["analytics"]["elapsed_ms"]
    print(f"\n{total} entries in {total_ms}ms\n")


if __name__ == "__main__":
    main()
