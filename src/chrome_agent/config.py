"""Centralized paths for fork-owned runtime state.

Every command resolves its state through this module so a configured root is
never mixed with the legacy ``/tmp/chrome-agent`` location.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


STATE_ROOT_ENV = "CHROME_AGENT_STATE_ROOT"
WINDOWS_DEFAULT_STATE_ROOT = Path("D:/tools/chrome-agent-data")
LEGACY_DEFAULT_STATE_ROOT = Path("/tmp/chrome-agent")


@dataclass(frozen=True)
class StatePaths:
    """All fork-owned locations derived from one root directory."""

    root: Path
    sessions: Path
    registry: Path
    profiles: Path
    cache: Path
    artifacts: Path
    temp: Path


def resolve_state_paths(state_root: str | os.PathLike[str] | None = None) -> StatePaths:
    """Resolve explicit root, then process environment, then platform default."""
    raw_root = state_root or os.environ.get(STATE_ROOT_ENV)
    root = Path(raw_root) if raw_root else (
        WINDOWS_DEFAULT_STATE_ROOT if sys.platform == "win32" else LEGACY_DEFAULT_STATE_ROOT
    )
    root = root.expanduser().resolve(strict=False)
    return StatePaths(
        root=root,
        sessions=root / "sessions",
        registry=root / "registry" / "registry.json",
        profiles=root / "profiles",
        cache=root / "cache",
        artifacts=root / "artifacts",
        temp=root / "temp",
    )


def is_owned_session_directory(path: str | os.PathLike[str], paths: StatePaths) -> bool:
    """Require an in-root, non-reparse session directory carrying our marker."""
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(paths.profiles.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return False
    if resolved.is_symlink() or not resolved.is_dir():
        return False
    marker = resolved / ".chrome-agent-owned.json"
    try:
        import json
        return json.loads(marker.read_text(encoding="utf-8")).get("session") == resolved.name
    except (OSError, ValueError, json.JSONDecodeError):
        return False
