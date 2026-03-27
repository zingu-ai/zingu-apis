# zingu-apis

Smart API client powered by [Zingu](https://zingu.dev) metadata. One function to fetch data from any API — pagination, auth, retries, and analytics handled automatically.

## Install

```bash
pip install zingu-apis
```

## Usage

```python
import zingu_apis

api = zingu_apis.api("dayinhistory")
result = api.fetch("today/events/")

# Iterate directly
for event in result:
    print(event["title"])

# Or unwrap: single-object APIs return the dict, multi-item APIs return the list
print(result.data)

# Index directly
print(result[0]["title"])

# See what came back — fields, timing, item count
print(result)

# Raw JSON
print(result.to_json())

# Metadata
print(result["analytics"])  # {elapsed_ms, pages_fetched, items_total, ...}
print(result["warnings"])   # non-fatal issues
print(result["errors"])     # errors (empty on success)
```

## Auth

```python
# Inline
api = zingu_apis.api("openweather", key="sk-abc123")

# Or via env var: export ZINGU_KEY_OPENWEATHER=sk-abc123
# Or via ~/.zingu/secrets file
api = zingu_apis.api("openweather")
```

Zingu metadata knows whether the key goes in a query param, header, or bearer token — you just provide the secret.

## Safety defaults

- `max_pages=10` — won't fetch more than 10 pages
- `page_delay=1.0s` for unauthenticated APIs, `0.2s` with auth — be polite
- `max_retries=2` — retries on 429/5xx with exponential backoff
- `max_chars=1_000_000` — truncates oversized items

```python
# Pruned for terminal display
result = api.fetch("today/events/", prune_profile="print")

# Strict mode — raises FetchError on errors instead of collecting them
result = api.fetch("today/events/", strict=True)

# Custom parser (e.g. JSON5, YAML)
import json5
result = api.fetch("endpoint", parser=json5.loads)
```

All API calls go directly to the target API — Zingu is only consulted for configuration metadata.
