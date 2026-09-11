"""Public-contract tests for the manual, local-only agent browser wrapper."""

import json
from pathlib import Path

import pytest

from integrations.windows import safe_browser


@pytest.mark.parametrize(
    "url",
    [
        "about:blank",
        "data:text/html,%3Ch1%3Elocal%3C/h1%3E",
        "http://localhost:3000/app?x=1",
        "https://localhost:8443/app",
        "http://127.0.0.1:8080/",
        "https://127.0.0.1:9443/",
        "http://[::1]:3000/",
        "https://[::1]:8443/",
    ],
)
def test_navigation_policy_allows_only_local_development_urls(url):
    assert safe_browser.validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://192.168.1.10/",
        "file:///D:/private.txt",
        "javascript:alert(1)",
        "chrome://version",
        "chrome-extension://abc/",
        "ftp://example.com/file",
        r"\\server\share\page.html",
        r"D:\local\page.html",
    ],
)
def test_navigation_policy_rejects_nonlocal_and_privileged_urls(url):
    with pytest.raises(safe_browser.SafeBrowserError):
        safe_browser.validate_url(url)


def test_navigation_policy_bounds_data_url_length():
    with pytest.raises(safe_browser.SafeBrowserError):
        safe_browser.validate_url("data:text/plain," + "x" * (safe_browser.MAX_DATA_URL_LENGTH + 1))


@pytest.mark.parametrize("unsafe", ["#ok\n", "#ok\x00", "x" * 257])
def test_selector_validation_rejects_control_and_oversized_input(unsafe):
    with pytest.raises(safe_browser.SafeBrowserError):
        safe_browser.validate_selector(unsafe)


def test_text_preserves_unicode_and_shell_metacharacters_as_data():
    text = 'مرحبا "quotes" % ! C:\\work\\file'
    assert safe_browser.validate_text(text) == text
    assert json.loads(safe_browser.render_json({"text": text}))["text"] == text


@pytest.mark.parametrize("unsafe", ["x" * 4097, "hello\x00world"])
def test_text_validation_has_a_bounded_literal_surface(unsafe):
    with pytest.raises(safe_browser.SafeBrowserError):
        safe_browser.validate_text(unsafe)


@pytest.mark.parametrize("name", ["../escape.png", "..\\escape.png", "C:/escape.png", "/tmp/escape.png"])
def test_screenshot_path_rejects_traversal_and_non_artifact_destinations(tmp_path, name):
    with pytest.raises(safe_browser.SafeBrowserError):
        safe_browser.artifact_path(name, artifacts_root=tmp_path / "artifacts")


def test_screenshot_path_is_contained_under_artifacts(tmp_path):
    output = safe_browser.artifact_path("result.png", artifacts_root=tmp_path / "artifacts")
    assert output == tmp_path / "artifacts" / "result.png"


def test_cli_surface_has_no_raw_cdp_or_javascript_operation():
    parser = safe_browser.build_parser()
    operations = {
        action.dest
        for action in parser._actions
        if getattr(action, "dest", None) == "operation"
    }
    assert operations == {"operation"}
    with pytest.raises(SystemExit):
        parser.parse_args(["cdp", "Runtime.evaluate"])
    with pytest.raises(SystemExit):
        parser.parse_args(["eval", "document.body.innerHTML"])
    with pytest.raises(SystemExit):
        parser.parse_args(["start", "--fingerprint", "profile.json"])
    with pytest.raises(SystemExit):
        parser.parse_args(["start", "--user-data-dir", r"C:\Users\hp"])


def test_wait_timeout_is_bounded():
    assert safe_browser.validate_timeout(1) == 1
    assert safe_browser.validate_timeout(safe_browser.MAX_WAIT_SECONDS) == safe_browser.MAX_WAIT_SECONDS
    with pytest.raises(safe_browser.SafeBrowserError):
        safe_browser.validate_timeout(0)
    with pytest.raises(safe_browser.SafeBrowserError):
        safe_browser.validate_timeout(safe_browser.MAX_WAIT_SECONDS + 1)


def test_type_sends_special_text_as_structured_cdp_data(monkeypatch):
    sent = []

    async def fake_send(method, params):
        sent.append((method, params))
        if method == "Runtime.evaluate":
            return {"result": {"value": {"found": True, "password": False}}}
        return {}

    wrapper = safe_browser.SafeBrowser()
    monkeypatch.setattr(wrapper, "page_send", fake_send)

    text = 'مرحبا "quotes" % ! C:\\work\\file'
    result = __import__("asyncio").run(wrapper.type_text("#note", text))

    assert result["typed"] is True
    assert ("Input.insertText", {"text": text}) in sent


def test_ambiguous_existing_managed_state_fails_closed(monkeypatch):
    class Active:
        alive = True

    monkeypatch.setattr(safe_browser, "enumerate_instances", lambda registry_path: [Active()])
    with pytest.raises(safe_browser.SafeBrowserError, match="active managed session"):
        safe_browser.ensure_no_active_session()


def test_importing_wrapper_does_not_launch_browser(monkeypatch):
    called = False

    async def fake_launch(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(safe_browser, "launch_browser", fake_launch)
    assert called is False


def test_non_start_cli_operation_cannot_launch_browser(monkeypatch):
    called = False

    async def fake_launch(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(safe_browser, "launch_browser", fake_launch)
    monkeypatch.setattr(safe_browser, "status", lambda: {"instances": []})
    assert safe_browser.main(["status"]) == 0
    assert called is False


def test_wrapper_uses_no_shell_execution():
    source = Path(safe_browser.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
