"""Two-layer cache: in-memory dict + disk JSON files."""

from __future__ import annotations

import json
import time
from pathlib import Path

_DEFAULT_TTL = 86400  # 24 hours
_CACHE_DIR = Path.home() / ".zingu" / "cache"
_memory: dict[str, tuple[float, dict]] = {}


def _disk_path(key: str) -> Path:
    safe = key.replace(":", "_").replace("/", "_")
    return _CACHE_DIR / f"{safe}.json"


def get(key: str, ttl: float = _DEFAULT_TTL) -> dict | None:
    """Return cached value if fresh, else None."""
    # Memory layer
    if key in _memory:
        ts, data = _memory[key]
        if time.time() - ts < ttl:
            return data

    # Disk layer
    path = _disk_path(key)
    if path.exists():
        try:
            mtime = path.stat().st_mtime
            if time.time() - mtime < ttl:
                data = json.loads(path.read_text())
                _memory[key] = (mtime, data)
                return data
        except (json.JSONDecodeError, OSError):
            pass

    return None


def put(key: str, data: dict) -> None:
    """Store value in both memory and disk."""
    now = time.time()
    _memory[key] = (now, data)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _disk_path(key).write_text(json.dumps(data))
    except OSError:
        pass  # Disk cache is best-effort
