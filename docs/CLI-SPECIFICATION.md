# zapi — Command-Line Interface for Zingu APIs

A CLI tool that turns any API in the Zingu catalog into a shell one-liner.
No manual headers, no URL construction, no pagination logic — just `zapi call <api> <method> [params]`.

## Motivation

Calling REST APIs from the terminal typically requires verbose `curl` commands with
manual header management, URL encoding, pagination handling, and output formatting.
The `zapi` CLI eliminates this by leveraging the Zingu metadata registry — the same
registry that powers the Python SDK — to auto-resolve authentication, pagination,
and endpoint structure.

**curl:**
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.dayinhistory.com/events/july/4/?page=1&limit=5" | jq '.results[]'
```

**zapi:**
```bash
zapi call dayinhistory events month=july day=4 --max-items 5
```

## Installation

`zapi` ships with the `zingu-apis` Python package. No separate install needed.

```bash
pip install zingu-apis
```

This registers the `zapi` console script automatically.

## Global Options

| Flag | Description |
|------|-------------|
| `--zingu-url URL` | Override the Zingu registry URL (e.g. `http://localhost:5002`) |

The registry URL can also be set via the `ZINGU_API_BASE_URL` environment variable.

## Command Structure

`zapi` has three subcommands:

```
zapi call   <api-slug> <method-or-path> [key=value ...] [--options]
zapi search <query>
zapi info   <api-slug> [method]
```

### `zapi call` — Fetch data from an API

```
zapi call <api-slug> <method-or-path> [key=value ...] [--options]
```

| Argument | Description |
|----------|-------------|
| `api-slug` | The Zingu registry slug for the API (e.g. `dayinhistory`, `openweather`) |
| `method-or-path` | Either a dynamic method name (e.g. `today_events`) or a path (e.g. `/today/events/`) |

#### Path Parameters

Path parameters are passed as `key=value` pairs. They fill placeholders in the
endpoint path template.

```bash
# These are equivalent:
zapi call dayinhistory events month=july day=4
zapi call dayinhistory /events/july/4/
```

#### Query Parameters

Query parameters use the same `key=value` syntax. The CLI distinguishes between
path parameters (those matching `{placeholders}` in the endpoint template) and
query parameters (everything else) automatically.

```bash
# "city" is a query parameter
zapi call openweather current city=Berlin units=metric
```

## Options for `zapi call`

### Fetch Control

| Flag | Default | Description |
|------|---------|-------------|
| `--max-items N` | unlimited | Stop after N items across all pages |
| `--max-pages N` | `10` | Maximum number of pages to fetch |
| `--max-chars N` | `1000000` | Truncate individual items exceeding N characters |
| `--page-delay SEC` | auto | Delay between paginated requests (seconds) |
| `--max-retries N` | `2` | Number of retries on 429/5xx errors |

### Output Format

| Flag | Description |
|------|-------------|
| `--json` | Raw JSON output (full FetchResult structure) |
| `--compact` | One JSON object per line — pipe-friendly (JSONL) |
| `--raw` | Print raw response content without processing |
| `--pretty` | Pretty-printed JSON with indentation (default for TTY) |
| `--no-color` | Disable colored output |

### Pruning

| Flag | Description |
|------|-------------|
| `--prune print` | Tight pruning for terminal display (60 chars, 20 items, depth 5) |
| `--prune compact` | Moderate pruning (120 chars, 50 items, depth 8) |
| `--prune safe` | Generous limits (50k chars, 500 items, depth 30) |
| `--prune llm` | Optimized for LLM consumption (1000 chars, 100 items, 100k total) |
| `--prune none` | No pruning |

### Truncation

| Flag | Default | Description |
|------|---------|-------------|
| `--truncation MODE` | `trailer` | How to truncate oversized items: `none`, `hard`, `trailer`, `smart` |

### Authentication

| Flag | Description |
|------|-------------|
| `--key VALUE` | Provide API key inline |

Authentication is resolved automatically in this order:

1. `--key` flag (inline)
2. Environment variable `ZINGU_KEY_{SLUG}` (e.g. `ZINGU_KEY_OPENWEATHER`)
3. Secrets file `~/.zingu/secrets`
4. Auth file `~/.config/zingu/auth.json`

### Output Selection

| Flag | Description |
|------|-------------|
| `--data-only` | Print only the `data` field (default) |
| `--analytics` | Include analytics (timing, pages fetched, bytes, etc.) |
| `--errors` | Include warnings and errors in output |
| `--full` | Print the complete FetchResult (data + analytics + warnings + errors) |
| `--url-only` | Print the resolved URL without making a request |
| `--curl` | Print the equivalent curl command instead of fetching (secrets use a temp env var) |

## Discovery Commands

### Search the API catalog

```bash
zapi search "weather"
zapi search "history events"
```

Searches the Zingu registry and prints matching APIs with their slugs and descriptions.
Output is minimal — one line per result:

```
openweather              Current weather, forecasts, and historical data
weatherapi               Real-time weather, astronomy, and time zone info
visualcrossing           Historical and forecast weather data
```

Use `zapi info <slug>` to get details on a specific API.

### Show API info

```bash
zapi info dayinhistory
```

Prints API-level metadata:

```
dayinhistory
  Base URL:    https://api.dayinhistory.com
  Auth:        none
  Endpoints:   3

  METHOD  NAME              PATH                    PAGINATION
  GET     today_events      /today/events/          page_number
  GET     today_births      /today/births/          page_number
  GET     events            /events/{month}/{day}/  page_number
```

### Show endpoint info

```bash
zapi info dayinhistory today_events
```

Prints endpoint-level detail including parameters, pagination config, and
example requests (if available from the registry):

```
dayinhistory — today_events
  Method:       GET
  Path:         /today/events/
  Description:  Get historical events for today's date
  Content-Type: application/json
  Pagination:   page_number (results_key: results)

  Parameters:   none

  Examples:
    zapi call dayinhistory today_events
    zapi call dayinhistory today_events --max-items 5
```

### List endpoints

```bash
zapi dayinhistory --help
```

Shortcut that behaves like `zapi info dayinhistory` — lists all endpoints
with their method names and path templates.

## Output Behavior

### TTY Detection

When stdout is a terminal (interactive use), `zapi` defaults to human-readable output:
- Pretty-printed with indentation
- Colored keys and values (unless `--no-color`)
- Analytics summary line at the end (timing, item count)

When stdout is a pipe or redirect, `zapi` defaults to machine-readable output:
- Compact JSON, one result per line
- No color codes
- No analytics summary

This can be overridden explicitly with `--pretty`, `--compact`, or `--json`.

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Fetch error (HTTP error, network failure) |
| `2` | Invalid arguments or unknown API/endpoint |
| `3` | Authentication missing or invalid |

### Stderr

Warnings (slow pages, truncation notices) are printed to stderr so they
don't interfere with piped output.

## Examples

### Basic fetch

```bash
# Fetch today's historical events
zapi call dayinhistory today_events

# Fetch events for a specific date
zapi call dayinhistory events month=july day=4
```

### Limiting output

```bash
# Only first 3 items, pruned for terminal
zapi call dayinhistory today_events --max-items 3 --prune print
```

### Piping to jq

```bash
# Extract just the titles
zapi call dayinhistory today_events --compact | jq -r '.title'
```

### Authenticated API

```bash
# Key from environment (ZINGU_KEY_OPENWEATHER)
zapi call openweather current city=London

# Key inline
zapi call openweather current city=London --key abc123
```

### Inspect before calling

```bash
# See what URL would be called
zapi call dayinhistory events month=july day=4 --url-only

# See endpoint metadata and examples
zapi info dayinhistory events
```

### LLM-friendly output

```bash
# Pruned and sized for feeding into an LLM context
zapi call dayinhistory today_events --prune llm --max-items 20
```

### Full result with analytics

```bash
zapi call dayinhistory today_events --full
# {
#   "data": [...],
#   "analytics": {
#     "elapsed_ms": 342,
#     "pages_fetched": 1,
#     "items_total": 15,
#     "bytes_total": 4821
#   },
#   "warnings": [],
#   "errors": []
# }
```

## Implementation Notes

### Package Integration

The CLI is implemented as a `console_scripts` entry point in `pyproject.toml`:

```toml
[project.scripts]
zapi = "zingu_apis.cli:main"
```

### Module Structure

The CLI lives in `src/zingu_apis/cli.py` and uses only the public SDK API:
- `zingu_apis.api()` for client creation
- `zingu_apis.search()` for catalog search
- `APIClient.help()`, `.info()`, `.tools()` for discovery
- `APIClient.fetch()` and dynamic methods for data fetching
- `Endpoint.fetch_url()` for `--url-only`

### Argument Parsing

Uses Python's `argparse` standard library — no additional dependencies.

### Dependencies

None beyond what `zingu-apis` already requires. The CLI adds zero new dependencies.

## Future: POST and Other HTTP Methods

The Zingu metadata registry stores the HTTP method (`GET`, `POST`, etc.) for each
endpoint. When the SDK adds support for non-GET requests, the CLI will use the
method from metadata automatically — the user never needs to specify it.

```bash
# The registry knows this endpoint is POST — no --method flag needed
zapi call myapi create_user name=Alice email=alice@example.com
```

For POST endpoints, `key=value` parameters become the JSON request body rather
than query parameters. The CLI detects this from the endpoint's HTTP method in
the metadata.

This requires SDK-level changes first:
- `APIClient` needs a generic `request()` method that supports POST/PUT/PATCH/DELETE
- `fetch()` needs to route through it based on `EndpointMeta.method`
- The CLI then gets this for free — no CLI changes needed beyond what's already wired
