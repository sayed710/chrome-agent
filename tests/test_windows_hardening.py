"""Windows-specific safety regression coverage for the Hussein fork."""

from pathlib import Path
import os
import subprocess
import sys


def test_state_root_precedence_explicit_then_environment_then_windows_default(monkeypatch):
    """One resolver chooses the state root for every command invocation."""
    from chrome_agent.config import WINDOWS_DEFAULT_STATE_ROOT, resolve_state_paths

    monkeypatch.setattr("chrome_agent.config.sys.platform", "win32")
    monkeypatch.setenv("CHROME_AGENT_STATE_ROOT", r"D:\env state")

    explicit = resolve_state_paths(r"D:\explicit state")
    from_env = resolve_state_paths()

    monkeypatch.delenv("CHROME_AGENT_STATE_ROOT")
    default = resolve_state_paths()

    assert explicit.root == Path(r"D:\explicit state")
    assert from_env.root == Path(r"D:\env state")
    assert default.root == WINDOWS_DEFAULT_STATE_ROOT
    assert explicit.registry == explicit.root / "registry" / "registry.json"
    assert explicit.sessions == explicit.root / "sessions"
    assert explicit.cache == explicit.root / "cache"


def test_cli_explicit_state_root_wins_over_process_environment(tmp_path):
    """All state-reading commands honor the global option before the environment."""
    env_root = tmp_path / "env-root"
    explicit_root = tmp_path / "explicit-root"
    registry = env_root / "registry" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        '{"from-env-01":{"port":1,"pid":999999,"browser_version":"x","user_data_dir":"x"}}',
        encoding="utf-8",
    )
    env = os.environ | {"CHROME_AGENT_STATE_ROOT": str(env_root)}
    result = subprocess.run(
        [sys.executable, "-m", "chrome_agent", "--state-root", str(explicit_root), "status"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "No instances registered" in result.stdout
    assert "from-env-01" not in result.stdout


def test_windows_chrome_discovery_precedence_and_spaces(monkeypatch):
    """Configured binary wins; HKCU and LocalAppData precede Program Files."""
    from chrome_agent import launcher

    explicit = r"D:\Browsers\Chrome عربي\chrome.exe"
    hkcu = r"C:\Users\hp\AppData\Local\Google\Chrome\Application\chrome.exe"
    local = r"C:\Users\hp\AppData\Local\Google\Chrome\Application\chrome.exe"
    program = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\hp\AppData\Local")
    monkeypatch.setattr(launcher, "_windows_hkcu_chrome", lambda: hkcu)
    monkeypatch.setattr(launcher, "_is_executable", lambda path: path in {explicit, hkcu, local, program})

    assert launcher.find_chrome_binary(chrome_binary=explicit) == explicit
    monkeypatch.setenv("CHROME_AGENT_CHROME_BINARY", explicit)
    assert launcher.find_chrome_binary() == explicit
    monkeypatch.delenv("CHROME_AGENT_CHROME_BINARY")
    assert launcher.find_chrome_binary() == hkcu
    monkeypatch.setattr(launcher, "_windows_hkcu_chrome", lambda: None)
    assert launcher.find_chrome_binary() == local
