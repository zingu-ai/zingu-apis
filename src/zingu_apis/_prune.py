"""Response pruning — limit string lengths, collection sizes, and nesting depth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PruneProfile:
    """Defines limits for pruning response data."""

    max_string: int = 0  # Max chars per string value. 0 = unlimited.
    max_list: int = 0  # Max elements per list. 0 = unlimited.
    max_keys: int = 0  # Max keys per dict. 0 = unlimited.
    max_depth: int = 0  # Max nesting levels. 0 = unlimited.
    max_total: int = 0  # Max total chars in serialized output. 0 = unlimited.
    trailer: str = "..."  # Appended to truncated strings/collections.


# Predefined profiles
PRUNE_PRINT = PruneProfile(max_string=60, max_list=20, max_keys=20, max_depth=5, trailer="...")
PRUNE_COMPACT = PruneProfile(max_string=120, max_list=50, max_keys=50, max_depth=8, trailer="...")
PRUNE_SAFE = PruneProfile(max_string=50_000, max_list=500, max_keys=500, max_depth=30, trailer="[…]")
PRUNE_NONE = PruneProfile()  # No pruning
PRUNE_LLM = PruneProfile(max_string=1000, max_list=100, max_keys=100, max_depth=10, max_total=100_000, trailer="[…]")

PROFILES = {
    "print": PRUNE_PRINT,
    "compact": PRUNE_COMPACT,
    "safe": PRUNE_SAFE,
    "none": PRUNE_NONE,
    "llm": PRUNE_LLM,
}


def prune(value: Any, profile: PruneProfile | str = PRUNE_SAFE, _depth: int = 0) -> Any:
    """Recursively prune a value according to a PruneProfile.

    Args:
        value: The data to prune (dict, list, string, or primitive).
        profile: A PruneProfile instance or a preset name ("print", "compact", "safe", "none", "llm").
        _depth: Internal depth counter — do not set manually.

    Returns:
        A pruned copy of the data. Original is not modified.
    """
    if isinstance(profile, str):
        profile = PROFILES.get(profile, PRUNE_SAFE)

    # Fast path: if no max_total and no per-item limits, just apply depth limit
    has_item_limits = any([
        profile.max_string,
        profile.max_list,
        profile.max_keys,
        profile.max_depth,
    ])

    if profile.max_total and has_item_limits:
        # Use stateful pruning with total tracking
        return _prune_with_total(value, profile, _depth)

    return _prune_simple(value, profile, _depth)


def _prune_simple(value: Any, profile: PruneProfile, _depth: int = 0) -> Any:
    """Prune without total limit tracking."""
    # Depth limit
    if profile.max_depth and _depth >= profile.max_depth:
        if isinstance(value, (dict, list)):
            return profile.trailer
        return value

    if isinstance(value, str):
        if profile.max_string and len(value) > profile.max_string:
            return value[: profile.max_string - len(profile.trailer)] + profile.trailer
        return value

    if isinstance(value, dict):
        keys = list(value.keys())
        truncated = profile.max_keys and len(keys) > profile.max_keys
        if truncated:
            keys = keys[: profile.max_keys]
        result = {k: _prune_simple(value[k], profile, _depth + 1) for k in keys}
        if truncated:
            result["_pruned"] = f"{len(value) - profile.max_keys} more keys"
        return result

    if isinstance(value, list):
        truncated = profile.max_list and len(value) > profile.max_list
        items = value[: profile.max_list] if truncated else value
        result = [_prune_simple(item, profile, _depth + 1) for item in items]
        if truncated:
            result.append(f"{profile.trailer} {len(value) - profile.max_list} more items")
        return result

    # Primitives (int, float, bool, None) — pass through
    return value


def _estimate_size(value: Any) -> int:
    """Rough estimate of serialized size for budget tracking."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (int, float, bool)):
        return len(str(value))
    if value is None:
        return 4  # "null"
    if isinstance(value, (dict, list)):
        return 100  # Rough estimate for structure overhead
    return 10


def _prune_with_total(value: Any, profile: PruneProfile, _depth: int = 0, state: dict | None = None) -> Any:
    """Prune with max_total tracking."""
    if state is None:
        state = {"total": 0}

    # Check if we've exceeded total budget
    if profile.max_total and state["total"] >= profile.max_total:
        return profile.trailer

    # Depth limit
    if profile.max_depth and _depth >= profile.max_depth:
        result = profile.trailer if isinstance(value, (dict, list)) else value
        state["total"] += _estimate_size(result)
        return result

    if isinstance(value, str):
        if profile.max_string and len(value) > profile.max_string:
            result = value[: profile.max_string - len(profile.trailer)] + profile.trailer
        else:
            result = value
        state["total"] += len(result)
        return result

    if isinstance(value, dict):
        keys = list(value.keys())
        truncated_keys = profile.max_keys and len(keys) > profile.max_keys
        if truncated_keys:
            keys = keys[: profile.max_keys]

        result = {}
        for k in keys:
            # Check budget before processing each key
            if profile.max_total and state["total"] >= profile.max_total:
                result["_pruned"] = profile.trailer
                break
            result[k] = _prune_with_total(value[k], profile, _depth + 1, state)

        if truncated_keys and "_pruned" not in result:
            result["_pruned"] = f"{len(value) - profile.max_keys} more keys"

        state["total"] += 2  # for {} overhead
        return result

    if isinstance(value, list):
        truncated_list = profile.max_list and len(value) > profile.max_list
        if truncated_list:
            items = value[: profile.max_list]
        else:
            items = value

        result = []
        for item in items:
            # Check budget before processing each item
            if profile.max_total and state["total"] >= profile.max_total:
                result.append(profile.trailer)
                break
            result.append(_prune_with_total(item, profile, _depth + 1, state))

        if truncated_list and result and result[-1] != profile.trailer:
            result.append(f"{profile.trailer} {len(value) - profile.max_list} more items")

        state["total"] += 2  # for [] overhead
        return result

    # Primitives (int, float, bool, None) — pass through
    state["total"] += _estimate_size(value)
    return value


# Keep backward compatibility - old prune function renamed to internal
