# Obtaining "This Day in History" Data with Python

**What happened on your birthday? On the day the moon landing took place?** The [Day in History API](/apis/dayinhistory.dev:day-in-history-api) serves structured historical events, births, and deaths for any date — no API key, no signup, just clean JSON over HTTPS.

## Obtaining the Client Object

One can obtain the slug-name of the API via the Zingu APIs web portal.
Then one can create a client object like so:

```python
import zingu_apis

api = zingu_apis.api("dayinhistory.dev:day-in-history-api")
```

## What the API Offers

```{python}
tools = api.tools()
print(tools)
```

The `.tools()` method returns a list of endpoints with description from the Zingu database. This command does not connect to the API directly.
In this example one can see from the returned dictionary that the API offers 6 endpoints corresponding to events, births, deaths for today or a specific day.

## Fetching Data Without the Boilerplate

Calling a paginated API normally requires a loop that tracks page numbers, follows `next` links, and collects results. The `zingu-apis` package handles all of that — plus retries, error handling, and analytics — in one call:

```python
import zingu_apis
slug = "dayinhistory.dev:day-in-history-api"
api = zingu_apis.api(slug)
result = api.fetch("/today/events/")

# See what fields are available
print(result)

# Access a single item directly
print(result[0]["title"])

# Or unwrap: single-object APIs return the dict, multi-item APIs return the list
print(result.data)
```

## Behind the scenes

The `fetch()` method handles:

- **Pagination** — follows pages automatically (knows this API uses `?page=N`)
- **Rate limiting** — waits 1s between pages for unauthenticated APIs (0.2s with auth)
- **Retries** — retries on 429/5xx with exponential backoff, respects `Retry-After` headers
- **Error handling** — never crashes; errors go into `result["errors"]`
- **Analytics** — elapsed time, pages fetched, bytes transferred

## Result Object

Every result has the same shape: 

- "data": parsed Python objects (lists, dicts) — the structured items
- "content": the raw response text from the API
- "analytics": a dictionary with analytics information like timing
- "warnings": a list potentially containing warning texts
- "errors": a list potentially containing error messages

You can iterate over the result object directly, index into it, or `print()` it for a summary.

## More Information about the API

One can obtain API-level information like authentication method and pagination style:

```python
info = api.info()
print(info['authentication']) # authentication method (none, api_key, bearer_token, etc.)
print(info['pagination'])     # pagination style (page_number, cursor, etc.)
print(info['base_url'])       # API base URL
```

## Inspecting an Endpoint

The `endpoint()` method returns an `Endpoint` object with methods to inspect its metadata:

```python
ep = api.endpoint("/today/events/")

print(ep.info())        # method, path, description, pagination style

print(ep.parameters())  # list of Parameter objects (name, type, description, required, default)

print(ep.examples())    # example requests with 'url' and 'description'
```

## Links

- **Our landing page:** [Day in History API](/apis/dayinhistory.dev:day-in-history-api)
- **API homepage:** [https://dayinhistory.dev](https://dayinhistory.dev)
- **API base URL:** `https://api.dayinhistory.dev/v1/`
- **zingu-apis package:** [https://pypi.org/project/zingu-apis/](https://pypi.org/project/zingu-apis/)

## Going Further

- **Historical timeline generator** — query every month/day combination for a specific year and build a chronological timeline, outputting it as CSV or HTML
- **Birthday twin finder** — enter your birthday, see which historical figures share the same date
- **"On This Day" static site** — pre-generate 366 pages and deploy as a zero-maintenance history site
- **Daily terminal greeting** — add a one-liner to your shell profile that prints a random historical event each time you open a terminal
- **History quiz game** — show event descriptions with the year blanked out, challenge players to guess within a decade
- **Era comparison tool** — fetch two dates centuries apart and display them side-by-side
