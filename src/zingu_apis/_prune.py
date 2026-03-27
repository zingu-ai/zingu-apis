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
    trailer: str = "..."  # Appended to truncated strings/collections.


# Predefined profiles
PRUNE_PRINT = PruneProfile(max_string=60, max_list=20, max_keys=20, max_depth=5, trailer="...")
PRUNE_COMPACT = PruneProfile(max_string=120, max_list=50, max_keys=50, max_depth=8, trailer="...")
PRUNE_SAFE = PruneProfile(max_string=50_000, max_list=500, max_keys=500, max_depth=30, trailer="[…]")
PRUNE_NONE = PruneProfile()  # No pruning

PROFILES = {
    "print": PRUNE_PRINT,
    "compact": PRUNE_COMPACT,
    "safe": PRUNE_SAFE,
    "none": PRUNE_NONE,
}


def prune(value: Any, profile: PruneProfile | str = PRUNE_SAFE, _depth: int = 0) -> Any:
    """Recursively prune a value according to a PruneProfile.

    Args:
        value: The data to prune (dict, list, string, or primitive).
        profile: A PruneProfile instance or a preset name ("print", "compact", "safe", "none").
        _depth: Internal depth counter — do not set manually.

    Returns:
        A pruned copy of the data. Original is not modified.
    """
    if isinstance(profile, str):
        profile = PROFILES.get(profile, PRUNE_SAFE)

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
        result = {k: prune(value[k], profile, _depth + 1) for k in keys}
        if truncated:
            result["_pruned"] = f"{len(value) - profile.max_keys} more keys"
        return result

    if isinstance(value, list):
        truncated = profile.max_list and len(value) > profile.max_list
        items = value[: profile.max_list] if truncated else value
        result = [prune(item, profile, _depth + 1) for item in items]
        if truncated:
            result.append(f"{profile.trailer} {len(value) - profile.max_list} more items")
        return result

    # Primitives (int, float, bool, None) — pass through
    return value
