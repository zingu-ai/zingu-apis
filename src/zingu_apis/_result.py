"""FetchResult — a dict-like result from api.fetch() with convenience methods."""

from __future__ import annotations

import json
from typing import Any, Iterator


class FetchResult(dict):
    """Result from api.fetch(). A dict with data, content, analytics, warnings, errors.

    - data: parsed Python objects (lists/dicts)
    - content: raw response text

    Iterating yields items from data directly.
    print() shows a human-readable summary.
    """

    def __iter__(self) -> Iterator[Any]:
        """Iterate over content items directly."""
        return iter(self.get("data", []))

    def __len__(self) -> int:
        """Number of content items."""
        return len(self.get("data", []))

    def __getitem__(self, key: Any) -> Any:
        """Access by index (int) for content items, or by key (str) for metadata."""
        if isinstance(key, (int, slice)):
            return self.get("data", [])[key]
        return super().__getitem__(key)

    @property
    def data(self) -> Any:
        """The content, unwrapped. Single item → returns the item. Multiple → returns the list."""
        content = self.get("data", [])
        if len(content) == 1:
            return content[0]
        return content

    def __repr__(self) -> str:
        return self.to_text()

    def __str__(self) -> str:
        return self.to_text()

    def to_json(self, indent: int = 2) -> str:
        """Return the full result as a JSON string."""
        return json.dumps(dict(self), indent=indent, default=str)

    def to_text(self, max_items: int = 3) -> str:
        """Return a human-readable summary."""
        lines = []
        analytics = self.get("analytics", {})
        content = self.get("data", [])
        warnings = self.get("warnings", [])
        errors = self.get("errors", [])

        # Header
        items_total = analytics.get("items_total", len(content))
        pages = analytics.get("pages_fetched", "?")
        elapsed = analytics.get("elapsed_ms", "?")
        lines.append(f"{items_total} items ({pages} page(s), {elapsed}ms)")

        # Errors
        if errors:
            for err in errors:
                lines.append(f"  ERROR: {err}")
            return "\n".join(lines)

        # Warnings
        for warn in warnings:
            lines.append(f"  WARNING: {warn}")

        # Show first N items
        if content:
            show = content[:max_items]
            lines.append("")
            for i, item in enumerate(show):
                lines.append(f"[{i}]")
                lines.extend(_format_item(item, indent=2))
            remaining = len(content) - len(show)
            if remaining > 0:
                lines.append(f"\n... and {remaining} more items")

        # Show available fields from first item
        if content and isinstance(content[0], dict):
            fields = list(content[0].keys())
            lines.append(f"\nFields: {', '.join(fields)}")

        return "\n".join(lines)


def _format_item(item: Any, indent: int = 0, max_depth: int = 3, _depth: int = 0) -> list[str]:
    """Format a single item for human-readable display."""
    prefix = " " * indent
    lines = []

    if _depth >= max_depth:
        lines.append(f"{prefix}...")
        return lines

    if isinstance(item, dict):
        for k, v in item.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{prefix}{k}:")
                lines.extend(_format_item(v, indent + 2, max_depth, _depth + 1))
            elif isinstance(v, str) and len(v) > 80:
                lines.append(f"{prefix}{k}: {v[:77]}...")
            else:
                lines.append(f"{prefix}{k}: {v}")
    elif isinstance(item, list):
        for i, v in enumerate(item[:5]):
            lines.append(f"{prefix}- {v}")
        if len(item) > 5:
            lines.append(f"{prefix}... {len(item) - 5} more")
    else:
        lines.append(f"{prefix}{item}")

    return lines
