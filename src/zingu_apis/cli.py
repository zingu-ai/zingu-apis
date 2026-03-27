"""zapi — Command-line interface for Zingu APIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import zingu_apis
from zingu_apis._errors import FetchError


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_json(obj: Any, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))
    else:
        print(json.dumps(obj, default=str, ensure_ascii=False))


def _print_compact(data: list) -> None:
    for item in data:
        print(json.dumps(item, default=str, ensure_ascii=False))


def _print_raw(content: Any) -> None:
    if isinstance(content, list):
        for page in content:
            print(page)
    else:
        print(content)


# ---------------------------------------------------------------------------
# Subcommand: search
# ---------------------------------------------------------------------------

def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    if not query:
        _warn("Usage: zapi search <query>")
        return 2

    results = zingu_apis.search(query)
    if not results:
        _warn("No APIs found.")
        return 0

    # Find max slug width for alignment
    max_slug = max(len(r.get("slug", r.get("id", ""))) for r in results)
    for r in results:
        slug = r.get("slug", r.get("id", ""))
        desc = r.get("description", r.get("name", ""))
        print(f"  {slug:<{max_slug + 2}} {desc}")

    return 0


# ---------------------------------------------------------------------------
# Subcommand: info
# ---------------------------------------------------------------------------

def cmd_info(args: argparse.Namespace) -> int:
    slug = args.api_slug

    try:
        client = zingu_apis.api(slug)
    except Exception as exc:
        _warn(f"Error: could not load API '{slug}': {exc}")
        return 2

    if args.method:
        return _info_endpoint(client, slug, args.method)
    return _info_api(client, slug)


def _info_api(client: zingu_apis.APIClient, slug: str) -> int:
    meta = client.meta
    info = client.info()
    tools = client.tools()

    print(f"\n  {slug}")
    print(f"    Base URL:    {info.get('base_url', '(unknown)')}")
    print(f"    Auth:        {info.get('authentication', 'none')}")
    print(f"    Endpoints:   {len(tools)}")
    print()

    if tools:
        # Column widths
        names = list(tools.keys())
        infos = list(tools.values())
        w_method = max(len(v["method"]) for v in infos)
        w_name = max(len(n) for n in names)
        w_path = max(len(v["path"]) for v in infos)

        header = f"    {'METHOD':<{w_method}}  {'NAME':<{w_name}}  {'PATH':<{w_path}}  PAGINATION"
        print(header)

        for name, ep in tools.items():
            # Find pagination style from meta
            pag = ""
            for emeta in meta.endpoints.values():
                if emeta.path == ep["path"]:
                    if emeta.pagination and emeta.pagination.style:
                        pag = emeta.pagination.style
                    break
            print(f"    {ep['method']:<{w_method}}  {name:<{w_name}}  {ep['path']:<{w_path}}  {pag}")

    print()
    return 0


def _info_endpoint(client: zingu_apis.APIClient, slug: str, method_name: str) -> int:
    tools = client.tools()
    if method_name not in tools:
        _warn(f"Error: no endpoint '{method_name}' in API '{slug}'.")
        _warn(f"Available: {', '.join(tools.keys())}")
        return 2

    ep_info = tools[method_name]
    path = ep_info["path"]

    # Get richer metadata from the endpoint object
    ep = client.endpoint(path)
    meta = ep.info()
    params = ep.parameters()

    print(f"\n  {slug} — {method_name}")
    print(f"    Method:       {meta.get('method', 'GET')}")
    print(f"    Path:         {meta.get('path', path)}")
    if meta.get("description"):
        print(f"    Description:  {meta['description']}")
    if meta.get("response_content_type"):
        print(f"    Content-Type: {meta['response_content_type']}")
    if meta.get("pagination"):
        print(f"    Pagination:   {meta['pagination']}")

    if params:
        print(f"\n    Parameters:")
        for p in params:
            req = " (required)" if p.required else ""
            print(f"      {p.name}: {p.type}{req}")
            if p.description:
                print(f"        {p.description}")
    else:
        print(f"\n    Parameters:   none")

    # Show examples
    examples = ep.examples()
    if examples:
        print(f"\n    Examples:")
        for ex in examples:
            if ex.get("description"):
                print(f"      # {ex['description']}")
            if ex.get("url"):
                print(f"      {ex['url']}")
    else:
        print(f"\n    Examples:")
        print(f"      zapi call {slug} {method_name}")
        print(f"      zapi call {slug} {method_name} --max-items 5")

    print()
    return 0


# ---------------------------------------------------------------------------
# Dump-on-prune helper
# ---------------------------------------------------------------------------

def _apply_dump_on_prune(result: dict, args: argparse.Namespace) -> dict:
    """Save full unpruned result to disk, then prune data for output."""
    from datetime import datetime
    from pathlib import Path
    from zingu_apis._prune import prune

    raw_data = result.get("data", [])
    raw_bytes = sum(len(json.dumps(item, default=str)) for item in raw_data)

    # Apply pruning to a copy of the data
    pruned_data = [prune(item, args.prune) for item in raw_data]
    pruned_bytes = sum(len(json.dumps(item, default=str)) for item in pruned_data)

    pruning_active = pruned_bytes < raw_bytes

    if pruning_active:
        # Save full unpruned result to dump directory
        dump_dir = Path(args.dump_on_prune).expanduser()
        dump_dir.mkdir(parents=True, exist_ok=True)

        slug_part = args.api_slug.replace(":", "_").replace("/", "_")
        path_part = args.method_or_path.strip("/").replace("/", "_")[:30]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_file = dump_dir / f"{slug_part}_{path_part}_{timestamp}.json"

        with open(dump_file, "w") as f:
            json.dump(raw_data, f, indent=2, default=str, ensure_ascii=False)

        dump_size = dump_file.stat().st_size
        result["dump_file"] = str(dump_file)
        result["dump_size_bytes"] = dump_size
        _warn(f"Dump: {dump_file} ({dump_size:,} bytes)")

    # Replace data with pruned version
    result["data"] = pruned_data
    result["pruning"] = {
        "active": pruning_active,
        "items_before": len(raw_data),
        "items_after": len(pruned_data),
        "bytes_before": raw_bytes,
        "bytes_after": pruned_bytes,
    }

    return result


# ---------------------------------------------------------------------------
# Subcommand: call
# ---------------------------------------------------------------------------

def cmd_call(args: argparse.Namespace) -> int:
    slug = args.api_slug
    method_or_path = args.method_or_path

    # Parse key=value pairs into params dict
    params: dict[str, str] = {}
    for kv in (args.params or []):
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k] = v
        else:
            _warn(f"Warning: ignoring parameter '{kv}' (expected key=value)")

    try:
        client = zingu_apis.api(slug, key=args.key)
    except Exception as exc:
        _warn(f"Error: could not load API '{slug}': {exc}")
        return 2

    # --url-only / --curl: resolve without fetching
    if args.url_only or args.curl:
        return _url_or_curl(client, method_or_path, params, curl=args.curl)

    # Determine if method_or_path is a dynamic method name or a path
    tools = client.tools()
    fetch_kwargs: dict[str, Any] = {}

    if args.max_items is not None:
        fetch_kwargs["max_items"] = args.max_items
    if args.max_pages is not None:
        fetch_kwargs["max_pages"] = args.max_pages
    if args.max_chars is not None:
        fetch_kwargs["max_chars"] = args.max_chars
    if args.truncation:
        fetch_kwargs["truncation"] = args.truncation
    if args.prune and not args.dump_on_prune:
        # Apply pruning inside fetch (normal mode)
        fetch_kwargs["prune_profile"] = args.prune
    # When dump-on-prune is set, we fetch WITHOUT pruning and apply it post-hoc
    if args.page_delay is not None:
        fetch_kwargs["page_delay"] = args.page_delay
    if args.max_retries is not None:
        fetch_kwargs["max_retries"] = args.max_retries

    # Verbose: show what we're about to call
    if args.verbose:
        base = client.base_url
        path = method_or_path if method_or_path not in tools else tools[method_or_path]["path"]
        _warn(f"Slug:     {client.slug}")
        _warn(f"Base URL: {base}")
        _warn(f"Path:     {path}")
        if params:
            _warn(f"Params:   {params}")
        _warn(f"URL:      {base}/{path.lstrip('/')}")

    try:
        if method_or_path in tools:
            # Dynamic method call
            method_fn = getattr(client, method_or_path)
            result = method_fn(**params, **fetch_kwargs)
        else:
            # Path-based call — separate path params from query params
            # Params matching {placeholders} in the path go as path params,
            # everything else goes as query params (**kwargs to fetch).
            import re
            placeholders = set(re.findall(r"\{(\w+)\}", method_or_path))
            path_params = {k: v for k, v in params.items() if k in placeholders}
            query_params = {k: v for k, v in params.items() if k not in placeholders}
            result = client.fetch(
                method_or_path,
                params=path_params or None,
                **query_params,
                **fetch_kwargs,
            )
    except FetchError as exc:
        _warn(f"Error: {exc}")
        return 1
    except Exception as exc:
        _warn(f"Error: {exc}")
        return 1

    # Print warnings to stderr
    for w in result.get("warnings", []):
        _warn(f"Warning: {w}")
    for e in result.get("errors", []):
        _warn(f"Error: {e}")

    if result.get("errors") and not result.get("data"):
        return 1

    # Dump-on-prune: save raw result, then apply pruning post-hoc
    if args.dump_on_prune and args.prune:
        result = _apply_dump_on_prune(result, args)

    # Determine output mode
    return _output_result(result, args)


def _url_or_curl(client: zingu_apis.APIClient, method_or_path: str, params: dict, curl: bool = False) -> int:
    tools = client.tools()
    if method_or_path in tools:
        path = tools[method_or_path]["path"]
    else:
        path = method_or_path

    ep = client.endpoint(path)
    url = ep.fetch_url(params or None)

    if not curl:
        print(url)
        return 0

    # Build curl command with auth headers — secrets go into a temp env var
    parts = ["curl", "-s"]
    req_params: dict[str, Any] = {}
    req_headers: dict[str, str] = {}
    client._auth.apply(req_params, req_headers)

    env_var = f"_ZAPI_KEY_{os.getpid()}"
    has_secret = False

    for header, value in req_headers.items():
        if client._auth.key and client._auth.key in value:
            # Replace the secret with an env var reference
            masked = value.replace(client._auth.key, f"${{{env_var}}}")
            parts.append(f"-H '{header}: {masked}'")
            has_secret = True
        else:
            parts.append(f"-H '{header}: {value}'")

    parts.append(f"'{url}'")
    curl_cmd = " \\\n  ".join(parts)

    if has_secret:
        print(f'export {env_var}="{client._auth.key}" && \\')
        print(f"  {curl_cmd} ; \\")
        print(f"  unset {env_var}")
    else:
        print(curl_cmd)

    return 0


def _output_result(result: dict, args: argparse.Namespace) -> int:
    data = result.get("data", [])
    tty = _is_tty()

    # Explicit format flags
    if args.raw:
        _print_raw(result.get("content", ""))
        return 0

    if args.full:
        _print_json(dict(result), pretty=tty)
        return 0

    if args.json:
        _print_json(dict(result), pretty=True)
        return 0

    if args.compact:
        _print_compact(data)
        _maybe_analytics(result, args)
        return 0

    if args.pretty or tty:
        _print_json(data, pretty=True)
        _maybe_analytics(result, args)
        return 0

    # Piped: compact by default
    _print_compact(data)
    return 0


def _maybe_analytics(result: dict, args: argparse.Namespace) -> None:
    if not (args.analytics or args.full):
        # In TTY mode, print a summary line to stderr
        if _is_tty():
            a = result.get("analytics", {})
            items = a.get("items_total", 0)
            pages = a.get("pages_fetched", 0)
            ms = a.get("elapsed_ms", 0)
            _warn(f"  {items} items, {pages} page(s), {ms}ms")
        return

    a = result.get("analytics", {})
    _warn(json.dumps(a, indent=2, default=str))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zapi",
        description="Command-line interface for Zingu APIs",
    )
    parser.add_argument(
        "--zingu-url",
        default=None,
        help="Override the Zingu registry URL (e.g. http://localhost:5002)",
    )
    sub = parser.add_subparsers(dest="command")

    # --- search ---
    p_search = sub.add_parser("search", help="Search the Zingu API catalog")
    p_search.add_argument("query", nargs="+", help="Search keywords")

    # --- info ---
    p_info = sub.add_parser("info", help="Show API or endpoint details")
    p_info.add_argument("api_slug", help="API slug")
    p_info.add_argument("method", nargs="?", help="Endpoint method name (optional)")

    # --- call ---
    p_call = sub.add_parser("call", help="Fetch data from an API endpoint")
    p_call.add_argument("api_slug", help="API slug")
    p_call.add_argument("method_or_path", help="Method name or endpoint path")
    p_call.add_argument("params", nargs="*", help="Parameters as key=value pairs")

    # Fetch control
    p_call.add_argument("--max-items", type=int, default=None)
    p_call.add_argument("--max-pages", type=int, default=None)
    p_call.add_argument("--max-chars", type=int, default=None)
    p_call.add_argument("--page-delay", type=float, default=None)
    p_call.add_argument("--max-retries", type=int, default=None)

    # Output format (mutually exclusive)
    fmt = p_call.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="Full result as pretty JSON")
    fmt.add_argument("--compact", action="store_true", help="One JSON object per line (JSONL)")
    fmt.add_argument("--raw", action="store_true", help="Raw response content")
    fmt.add_argument("--pretty", action="store_true", help="Pretty-printed JSON")

    # Pruning & truncation
    p_call.add_argument("--prune", choices=["print", "compact", "safe", "llm", "none"], default=None)
    p_call.add_argument("--truncation", choices=["none", "hard", "trailer", "smart"], default=None)
    p_call.add_argument("--dump-on-prune", metavar="DIR", default=None,
                        help="Auto-save full unpruned response to DIR if pruning reduces the result")

    # Auth
    p_call.add_argument("--key", default=None, help="API key")

    # Output selection
    p_call.add_argument("--analytics", action="store_true", help="Show analytics")
    p_call.add_argument("--full", action="store_true", help="Full result with analytics/warnings/errors")
    p_call.add_argument("--url-only", action="store_true", help="Print resolved URL without fetching")
    p_call.add_argument("--curl", action="store_true", help="Print equivalent curl command instead of fetching")
    p_call.add_argument("-v", "--verbose", action="store_true", help="Show resolved URL and request details to stderr")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.zingu_url:
        zingu_apis.configure(base_url=args.zingu_url)

    if not args.command:
        parser.print_help()
        sys.exit(2)

    handlers = {
        "search": cmd_search,
        "info": cmd_info,
        "call": cmd_call,
    }
    sys.exit(handlers[args.command](args))


if __name__ == "__main__":
    main()
