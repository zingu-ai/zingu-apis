# Zingu APIs SDK Documentation

Official Python SDK for interacting with the Zingu API catalog.

## Quick Start

```python
import zingu_apis

# Get an API handle by slug
api = zingu_apis.api("dayinhistory")

# Call endpoint as method with parameters
result = api.events_month_day(month="july", day=4, max_items=5)

# Iterate over results
for event in result:
    print(f"{event['year']}: {event['title']}")
```

## Installation

```bash
pip install git+https://github.com/zingu-ai/zingu-apis.git
```

## API Reference

### Creating an API Client

```python
import zingu_apis

# Basic usage (no auth required for most APIs)
api = zingu_apis.api("dayinhistory")

# With API key for authenticated APIs
api = zingu_apis.api("stripe", key="your-api-key")
```

### Calling Endpoints

The SDK provides **4 ways** to call endpoints:

#### 1. Dynamic Method (Recommended)

```python
result = api.events_month_day(month="july", day=4, max_items=5)
```

#### 2. Fetch with Path Template + Dict Params

```python
result = api.fetch(
    "events/{month}/{day}",
    params={"month": "july", "day": 4},
    max_items=5
)
```

#### 3. Fetch with Path Template + List Params

```python
result = api.fetch(
    "events/{month}/{day}",
    params=["july", 4],
    max_items=5
)
```

#### 4. Fetch with Literal Path

```python
result = api.fetch("events/july/4", max_items=5)
```

### Discovery Methods

```python
# Show all available methods with signatures
print(api.help())

# Get method name from path
name = api.get_method_name("events/month/day")  # -> "events_month_day"

# Get callable method from path
method = api.get_method("events/month/day")
result = method(month="july", day=4)

# Get parameter info
params = api.get_method_parameters("events/month/day")
# -> [{"name": "month", "type": "string"}, {"name": "day", "type": "string"}]

# Get all endpoint metadata
endpoints = api.tools()
```

### Endpoint Metadata

Each endpoint method has a `.info()` function that returns metadata:

```python
method = api.get_method("events/month/day")
info = method.info()

print(info)
# {
#     'method': 'GET',
#     'path': '/events/{month}/{day}',
#     'description': 'Get historical events for a specific date',
#     'response_content_type': 'application/json',
#     'pagination': {'style': 'page_number', 'results_key': 'results'},
#     'parameters': None  # or dict of parameter metadata
# }
```

### Configuration

```python
import zingu_apis

# Configure for local development (optional)
zingu_apis.configure(base_url="http://localhost:5002")

# Get API-level metadata
info = api.info()
print(info["base_url"])      # API base URL
print(info["authentication"])  # Auth type
```

## Features

- **Type Safety** — Full Python type hints included
- **Authentication** — Built-in API key support
- **Auto-Retry** — Automatic retries with exponential backoff
- **Rate Limiting** — Respects API rate limits
- **Pagination** — Automatic pagination handling
- **Caching** — Metadata caching for repeated calls
- **Error Handling** — Structured exceptions

## Examples

See the `examples/` directory for complete working examples.

## Support

- GitHub Issues: https://github.com/zingu-ai/zingu-apis/issues
- GitHub Discussions: https://github.com/zingu-ai/zingu-apis/discussions
