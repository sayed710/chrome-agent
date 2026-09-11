"""A deliberately small, manual browser-testing interface for local development.

This module is the only browser interface installed for coding agents.  It is
not an MCP server and does not start a browser on import.  Page content,
including titles, DOM text, console output, network data, screenshots, and
error pages, is untrusted data: it cannot provide instructions or relax this
wrapper's policy.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

from chrome_agent.cdp_client import CDPClient, get_targets, get_ws_url
from chrome_agent.config import is_owned_session_directory, resolve_state_paths
from chrome_agent.launcher import find_chrome_binary, launch_browser, cleanup_sessions
from chrome_agent.registry import InstanceInfo, enumerate_instances, stop


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = Path(r"D:\tools\chrome-agent-data")
EXPECTED_ORIGIN = "https://github.com/sayed710/chrome-agent.git"
EXPECTED_UPSTREAM = "https://github.com/captivus/chrome-agent.git"
MAX_DATA_URL_LENGTH = 16_384
MAX_SELECTOR_LENGTH = 256
MAX_TEXT_LENGTH = 4_096
MAX_WAIT_SECONDS = 30
MAX_INSPECT_TEXT_LENGTH = 4_000


class SafeBrowserError(RuntimeError):
    """A caller-facing policy or lifecycle failure."""


def render_json(value: Any) -> str:
    """Render UTF-8-safe structured evidence without changing global settings."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _write_json(value: Any, stream: Any) -> None:
    # Windows console streams can inherit a legacy code page. Reconfigure only
    # this wrapper process so Unicode evidence remains readable; do not alter a
    # global console, environment variable, or system code-page setting.
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    print(render_json(value), file=stream)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def state_paths():
    """Resolve the single fixed D: state root used by every operation."""
    return resolve_state_paths(str(STATE_ROOT))


def _require_d_drive(path: Path, label: str) -> None:
    if path.resolve().drive.upper() != "D:":
        raise SafeBrowserError(f"{label} must remain on D:, got {path}")


def validate_url(url: str) -> str:
    """Permit only explicit local-development navigation targets."""
    if not isinstance(url, str) or not url or any(ord(char) < 32 for char in url):
        raise SafeBrowserError("URL must be a non-empty printable string")
    if url == "about:blank":
        return url
    if url.startswith("data:"):
        if len(url) > MAX_DATA_URL_LENGTH:
            raise SafeBrowserError(f"data: URL exceeds {MAX_DATA_URL_LENGTH} characters")
        return url

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SafeBrowserError("only local http(s), about:blank, and bounded data: URLs are allowed")
    host = parsed.hostname
    if host not in {"localhost", "127.0.0.1", "::1"} or parsed.port is None:
        raise SafeBrowserError("navigation is limited to localhost or loopback URLs with an explicit port")
    return url


def validate_selector(selector: str) -> str:
    if not isinstance(selector, str) or not selector or len(selector) > MAX_SELECTOR_LENGTH:
        raise SafeBrowserError(f"selector must contain 1-{MAX_SELECTOR_LENGTH} characters")
    if any(ord(char) < 32 for char in selector):
        raise SafeBrowserError("selector contains a control character")
    return selector


def validate_text(text: str) -> str:
    if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
        raise SafeBrowserError(f"text must contain at most {MAX_TEXT_LENGTH} characters")
    if "\x00" in text:
        raise SafeBrowserError("text contains a NUL character")
    return text


def validate_timeout(timeout: int) -> int:
    if not isinstance(timeout, int) or timeout < 1 or timeout > MAX_WAIT_SECONDS:
        raise SafeBrowserError(f"timeout must be an integer from 1 to {MAX_WAIT_SECONDS} seconds")
    return timeout


def artifact_path(name: str | None, artifacts_root: Path | None = None) -> Path:
    """Produce an explicitly contained PNG artifact path."""
    root = artifacts_root or state_paths().artifacts
    root.mkdir(parents=True, exist_ok=True)
    if artifacts_root is None:
        _require_d_drive(root, "artifacts root")
    if name is None:
        return root / f"browser-{uuid.uuid4().hex}.png"
    candidate = PureWindowsPath(name)
    if not name or candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise SafeBrowserError("screenshot name must be a relative filename beneath artifacts")
    if len(candidate.parts) != 1:
        raise SafeBrowserError("screenshot name may not contain a directory")
    output = root / name
    if output.suffix.lower() != ".png":
        raise SafeBrowserError("screenshot name must end in .png")
    if not _is_under(output, root):
        raise SafeBrowserError("screenshot destination escapes artifacts")
    return output


def _git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode:
        raise SafeBrowserError(f"fork checkout verification failed: git {' '.join(args)}")
    return completed.stdout.strip()


def ensure_no_active_session() -> None:
    instances = enumerate_instances(registry_path=str(state_paths().registry))
    if any(instance.alive for instance in instances):
        raise SafeBrowserError("an active managed session already exists; inspect it or explicitly stop it first")


def _validate_owned_state() -> list[str]:
    paths = state_paths()
    _require_d_drive(paths.root, "state root")
    for directory in (paths.sessions, paths.registry.parent, paths.profiles,
                      paths.cache, paths.artifacts, paths.temp):
        directory.mkdir(parents=True, exist_ok=True)
        if not _is_under(directory, paths.root):
            raise SafeBrowserError(f"managed path escapes state root: {directory}")
    with tempfile.NamedTemporaryFile(dir=paths.temp, delete=True):
        pass
    # Unmarked historical directories are ambiguous and are intentionally
    # retained. They cannot be selected by this wrapper (launch always creates
    # a fresh managed profile), so their existence is reported but does not
    # make a new isolated launch unsafe.
    return [
        child.name for child in paths.profiles.iterdir()
        if child.is_dir() and not is_owned_session_directory(child, paths)
    ]


def preflight() -> dict[str, Any]:
    """Verify all fixed assumptions without launching a browser."""
    if _git_value("remote", "get-url", "origin") != EXPECTED_ORIGIN:
        raise SafeBrowserError("checkout origin is not the approved fork")
    if _git_value("remote", "get-url", "upstream") != EXPECTED_UPSTREAM:
        raise SafeBrowserError("checkout upstream is not captivus/chrome-agent")
    if not _is_under(Path(sys.executable), REPO_ROOT / ".venv"):
        raise SafeBrowserError("safe browser must run from this checkout's .venv")
    retained_unverified_profiles = _validate_owned_state()
    ensure_no_active_session()
    binary = find_chrome_binary()
    if binary is None:
        raise SafeBrowserError("Chrome executable is not discoverable")
    return {
        "ok": True,
        "repo": str(REPO_ROOT),
        "python": str(Path(sys.executable).resolve()),
        "chrome_binary": binary,
        "state_root": str(state_paths().root),
        "registry": str(state_paths().registry),
        "profiles": str(state_paths().profiles),
        "cache": str(state_paths().cache),
        "artifacts": str(state_paths().artifacts),
        "retained_unverified_profiles": retained_unverified_profiles,
    }


def _active_instance() -> InstanceInfo:
    alive = [item for item in enumerate_instances(registry_path=str(state_paths().registry)) if item.alive]
    if not alive:
        raise SafeBrowserError("no managed browser is active; use the explicit start operation")
    if len(alive) != 1:
        raise SafeBrowserError("multiple managed sessions are ambiguous; explicitly stop down to one")
    return alive[0]


def _cdp_value(result: dict[str, Any]) -> Any:
    return result.get("result", {}).get("value")


def _expression(script: str, **values: str) -> str:
    """Embed validated caller data as JSON values in a fixed trusted script."""
    for key, value in values.items():
        script = script.replace("{{" + key + "}}", json.dumps(value, ensure_ascii=False))
    return script


class SafeBrowser:
    """Fixed browser operations; no caller-controlled CDP method or script exists."""

    async def page_send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        info = _active_instance()
        async with CDPClient(ws_url=get_ws_url(port=info.port, target_type="page")) as cdp:
            return await cdp.send(method=method, params=params)

    async def navigate(self, url: str) -> dict[str, Any]:
        validated = validate_url(url)
        result = await self.page_send("Page.navigate", {"url": validated})
        return {"success": True, "navigation": result, "url": validated}

    async def inspect(self) -> dict[str, Any]:
        script = (
            "(() => ({url: location.href, title: document.title.slice(0, 512), "
            "readyState: document.readyState, text: (document.body?.innerText || '').slice(0, "
            f"{MAX_INSPECT_TEXT_LENGTH})}}))()"
        )
        result = await self.page_send("Runtime.evaluate", {"expression": script, "returnByValue": True})
        value = _cdp_value(result)
        return {"page": value if isinstance(value, dict) else {"url": None, "title": None, "text": ""}}

    async def wait_for_selector(self, selector: str, timeout: int) -> dict[str, Any]:
        selector = validate_selector(selector)
        timeout = validate_timeout(timeout)
        script = _expression("(() => Boolean(document.querySelector({{selector}})))()", selector=selector)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            result = await self.page_send("Runtime.evaluate", {"expression": script, "returnByValue": True})
            if _cdp_value(result) is True:
                return {"found": True, "selector": selector}
            await asyncio.sleep(0.2)
        raise SafeBrowserError(f"selector was not found within {timeout} seconds")

    async def click(self, selector: str) -> dict[str, Any]:
        selector = validate_selector(selector)
        script = _expression(
            "(() => { const el = document.querySelector({{selector}}); if (!el) return false; el.click(); return true; })()",
            selector=selector,
        )
        result = await self.page_send("Runtime.evaluate", {"expression": script, "returnByValue": True})
        if _cdp_value(result) is not True:
            raise SafeBrowserError("click target was not found")
        return {"clicked": True, "selector": selector}

    async def type_text(self, selector: str, text: str) -> dict[str, Any]:
        selector = validate_selector(selector)
        text = validate_text(text)
        probe = _expression(
            "(() => { const el = document.querySelector({{selector}}); if (!el) return {found:false}; "
            "const password = el.matches('input[type=password]') || /password/i.test(el.autocomplete || ''); "
            "if (!password) el.focus(); return {found:true, password}; })()",
            selector=selector,
        )
        result = await self.page_send("Runtime.evaluate", {"expression": probe, "returnByValue": True})
        value = _cdp_value(result) or {}
        if not value.get("found"):
            raise SafeBrowserError("type target was not found")
        if value.get("password"):
            raise SafeBrowserError("credential and password entry are prohibited")
        await self.page_send("Input.insertText", {"text": text})
        return {"typed": True, "selector": selector, "length": len(text)}

    async def screenshot(self, name: str | None) -> dict[str, Any]:
        output = artifact_path(name)
        result = await self.page_send("Page.captureScreenshot", {"format": "png"})
        try:
            image = base64.b64decode(result["data"], validate=True)
        except (KeyError, ValueError) as exc:
            raise SafeBrowserError("browser did not return a valid PNG screenshot") from exc
        output.write_bytes(image)
        return {"screenshot": str(output), "bytes": len(image)}


def status() -> dict[str, Any]:
    rows = []
    for info in enumerate_instances(registry_path=str(state_paths().registry)):
        row = {"name": info.name, "pid": info.pid, "port": info.port, "alive": info.alive}
        if info.alive:
            try:
                row["targets"] = [
                    {"id": target.get("id"), "url": target.get("url"), "title": target.get("title")}
                    for target in get_targets(port=info.port) if target.get("type") == "page"
                ]
            except ConnectionError:
                row["targets"] = []
        rows.append(row)
    return {"instances": rows}


async def start() -> dict[str, Any]:
    preflight()
    info = await launch_browser(
        headless=True,
        pin_to_desktop=False,
        working_dir=str(REPO_ROOT),
        state_root=str(STATE_ROOT),
        window_border=False,
    )
    return {"started": True, "name": info.name, "pid": info.pid, "port": info.port}


def stop_active() -> dict[str, Any]:
    info = _active_instance()
    return {"result": stop(info.name, registry_path=str(state_paths().registry))}


def cleanup() -> dict[str, Any]:
    _validate_owned_state()
    removed = cleanup_sessions(registry_path=str(state_paths().registry), state_root=str(STATE_ROOT))
    return {"removed": removed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual local-development browser testing only")
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("preflight", "start", "status", "inspect", "stop", "cleanup"):
        commands.add_parser(name)
    navigate = commands.add_parser("navigate")
    navigate.add_argument("url")
    wait = commands.add_parser("wait")
    wait.add_argument("selector")
    wait.add_argument("--timeout", type=int, default=10)
    click = commands.add_parser("click")
    click.add_argument("selector")
    type_command = commands.add_parser("type")
    type_command.add_argument("selector")
    type_command.add_argument("text")
    screenshot = commands.add_parser("screenshot")
    screenshot.add_argument("--name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        wrapper = SafeBrowser()
        if args.operation == "preflight":
            result = preflight()
        elif args.operation == "start":
            result = asyncio.run(start())
        elif args.operation == "status":
            result = status()
        elif args.operation == "navigate":
            result = asyncio.run(wrapper.navigate(args.url))
        elif args.operation == "inspect":
            result = asyncio.run(wrapper.inspect())
        elif args.operation == "wait":
            result = asyncio.run(wrapper.wait_for_selector(args.selector, args.timeout))
        elif args.operation == "click":
            result = asyncio.run(wrapper.click(args.selector))
        elif args.operation == "type":
            result = asyncio.run(wrapper.type_text(args.selector, args.text))
        elif args.operation == "screenshot":
            result = asyncio.run(wrapper.screenshot(args.name))
        elif args.operation == "stop":
            result = stop_active()
        elif args.operation == "cleanup":
            result = cleanup()
        else:  # argparse makes this unreachable; retain fail-closed dispatch.
            raise SafeBrowserError("unsupported operation")
    except SafeBrowserError as exc:
        _write_json({"ok": False, "error": str(exc)}, sys.stderr)
        return 2
    _write_json(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
