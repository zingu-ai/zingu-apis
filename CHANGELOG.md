# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-04-08

### Added
- Surface connection errors with clear messages
- Search suggestions when queries return empty results
- `__version__` attribute accessible via `zingu_apis.__version__`

### Fixed
- URL path overlap when `base_url` includes a path prefix

## [0.5.0] - Rename & MCP

### Changed
- Renamed `fetch()` to `call()` (`fetch` kept as alias)

### Added
- MCP server (`zingu-mcp` CLI entry point)

## [0.4.0] - CLI & Pruning

### Added
- CLI tool (`zapi`) with dump-on-prune and verbose flag
- Prune profile `"llm"` for LLM-friendly output

### Fixed
- Query params handling bug in CLI

## [0.3.0] - Introspection

### Added
- `.info()` method on endpoint methods
- `get_method_name`, `get_method`, `get_method_parameters` helpers

## [0.2.0] - Documentation

### Added
- Package documentation
- Link to documentation in project metadata

## [0.1.0] - Initial Release

### Added
- `APIClient` with pagination-aware fetching
- Zingu metadata integration (`configure`, `fetch_meta`, `search`)
- Pruning system with profiles (`PRUNE_PRINT`, `PRUNE_COMPACT`, `PRUNE_SAFE`, `PRUNE_NONE`)
- Auth resolution from env vars and `~/.config/zingu/auth.json`
- Truncation strategies (`none`, `hard`, `trailer`, `smart`)
