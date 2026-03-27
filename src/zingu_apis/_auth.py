"""Auth resolution — attach credentials to API requests automatically.

Resolution order:
1. Explicit key passed to api() or fetch()
2. Environment variable: ZINGU_KEY_{SLUG_NORMALIZED}
3. Secrets file: ~/.zingu/secrets (simple key=value format)
4. Auth file: ~/.config/zingu/auth.json (richer format with placement overrides)
5. No auth (for APIs that don't require it)

The auth *type* (bearer, query param, header, etc.) comes from Zingu metadata.
The user only provides the secret — we put it in the right place.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ZINGU_DIR = Path.home() / ".zingu"
_SECRETS_FILE = _ZINGU_DIR / "secrets"
_AUTH_FILE = Path.home() / ".config" / "zingu" / "auth.json"


@dataclass
class AuthConfig:
    """Resolved auth configuration for an API."""

    auth_type: str  # none, api_key, bearer_token, custom_header
    key: str | None = None
    location: str | None = None  # query, header
    param_name: str | None = None  # e.g. "appid", "api_key", "X-Api-Key"

    def apply(self, session_params: dict, session_headers: dict) -> None:
        """Apply auth to request params/headers in place."""
        if not self.key or self.auth_type == "none":
            return
        if self.auth_type == "bearer_token":
            session_headers["Authorization"] = f"Bearer {self.key}"
        elif self.auth_type == "api_key" and self.location == "query":
            param = self.param_name or "api_key"
            session_params[param] = self.key
        elif self.auth_type == "api_key" and self.location == "header":
            header = self.param_name or "X-Api-Key"
            session_headers[header] = self.key
        elif self.auth_type == "custom_header":
            header = self.param_name or "Authorization"
            session_headers[header] = self.key
        elif self.key:
            # Fallback: if we have a key but don't know where to put it,
            # try bearer token (most common)
            session_headers["Authorization"] = f"Bearer {self.key}"


def _slug_to_env_var(slug: str) -> str:
    """Convert a slug like 'openweather:weather-api' to 'ZINGU_KEY_OPENWEATHER_WEATHER_API'."""
    normalized = re.sub(r"[^a-zA-Z0-9]", "_", slug).upper()
    return f"ZINGU_KEY_{normalized}"


def _load_secrets_file() -> dict[str, str]:
    """Load secrets from ~/.zingu/secrets.

    Format (one per line, like .env):
        dayinhistory.dev:day-in-history-api=none
        openweather:weather-api=sk-abc123
        nasa:apod-api=DEMO_KEY
        # comments and blank lines are ignored
    """
    secrets = {}
    if not _SECRETS_FILE.exists():
        return secrets
    try:
        for line in _SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip inline comments (but not # inside values)
            if "=" not in line:
                continue
            slug, _, value = line.partition("=")
            slug = slug.strip()
            value = value.strip()
            # Handle inline placement hints: sk-abc123  # query:appid
            if "  #" in value:
                value = value.split("  #")[0].strip()
            if slug and value:
                secrets[slug] = value
    except OSError:
        pass
    return secrets


def _load_secrets_file_hints(slug: str) -> dict[str, str]:
    """Extract placement hints from ~/.zingu/secrets for a given slug.

    Format: value  # location:param_name
    Example: sk-abc123  # query:appid
    """
    if not _SECRETS_FILE.exists():
        return {}
    try:
        for line in _SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            line_slug, _, rest = line.partition("=")
            if line_slug.strip() != slug:
                continue
            if "  #" in rest:
                _, _, hint = rest.partition("  #")
                hint = hint.strip()
                if ":" in hint:
                    location, _, param = hint.partition(":")
                    return {"location": location.strip(), "param": param.strip()}
            break
    except OSError:
        pass
    return {}


def _load_auth_file() -> dict[str, Any]:
    """Load auth config from ~/.config/zingu/auth.json."""
    if _AUTH_FILE.exists():
        try:
            return json.loads(_AUTH_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def resolve_auth(slug: str, auth_type: str, key: str | None = None) -> AuthConfig:
    """Resolve auth credentials for an API.

    Args:
        slug: API slug from Zingu database.
        auth_type: Auth type from metadata (none, api_key, bearer_token, etc.).
        key: Explicit key passed by the user. Takes priority over all other sources.

    Returns:
        AuthConfig with resolved credentials and placement info.
    """
    location = None
    param_name = None

    # Layer 4: auth.json (richest format, lowest priority for key)
    auth_data = _load_auth_file()
    file_entry = auth_data.get(slug, {})
    if isinstance(file_entry, str):
        file_entry = {"key": file_entry}

    # Layer 3: ~/.zingu/secrets
    secrets = _load_secrets_file()
    secrets_key = secrets.get(slug)
    secrets_hints = _load_secrets_file_hints(slug)

    # Resolve the key: explicit > env var > secrets file > auth.json
    if key is None:
        env_var = _slug_to_env_var(slug)
        key = os.environ.get(env_var)
    if key is None:
        key = secrets_key
    if key is None:
        key = file_entry.get("key")

    # "none" in secrets file means explicitly no auth
    if key == "none":
        key = None

    # Resolve placement: secrets hints > auth.json > defaults
    if secrets_hints:
        location = secrets_hints.get("location", location)
        param_name = secrets_hints.get("param", param_name)
    if file_entry:
        auth_type = file_entry.get("type", auth_type)
        location = file_entry.get("location", location) if not secrets_hints else location
        param_name = file_entry.get("param", param_name) if not secrets_hints else param_name

    # If user explicitly provided a key but metadata says "none", upgrade to bearer
    if key and (not auth_type or auth_type == "none"):
        auth_type = "bearer_token"

    # If auth_type is still generic, infer location
    if auth_type == "api_key" and location is None:
        location = "query"  # most common for api_key type

    return AuthConfig(
        auth_type=auth_type or "none",
        key=key,
        location=location,
        param_name=param_name,
    )
