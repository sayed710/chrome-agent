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
