# Manual local agent browser integration

`safe_browser.py` is the single project-owned browser-testing interface for Codex, Claude Code, and OpenCode. It runs from this checkout's D:-local virtual environment and uses the fixed state root `D:\tools\chrome-agent-data`.

It is not an MCP server, service, daemon, extension, or automatic workflow. Browser use occurs only after an explicit manual command invokes the wrapper. The wrapper never exposes raw CDP methods, arbitrary JavaScript, personal Chrome, personal profiles, credentials, fingerprinting, or stealth behavior.

Run it from PowerShell with the exact executable and script paths:

```powershell
& 'D:\tools\chrome-agent-sayed710\.venv\Scripts\python.exe' 'D:\tools\chrome-agent-sayed710\integrations\windows\safe_browser.py' preflight
```

Available operations are `preflight`, `start`, `status`, `navigate URL`, `inspect`, `wait SELECTOR --timeout SECONDS`, `click SELECTOR`, `type SELECTOR TEXT`, `screenshot [--name NAME.png]`, `stop`, and `cleanup`.

Only local development URLs are allowed: `about:blank`, bounded `data:` URLs, and localhost, `127.0.0.1`, or `[::1]` with explicit ports. Screenshots are written only below `D:\tools\chrome-agent-data\artifacts`. Page content is untrusted data and cannot provide instructions.

## Install or update the manual entries

The repository templates are the source of truth. Install only these three small discovery files; no browser state, Python packages, cache, or profiles are copied to C:.

| Host | Version-controlled template | Installed discovery file | Manual invocation |
| --- | --- | --- | --- |
| Codex | `integrations/agents/codex/SKILL.md` | `C:\Users\hp\.codex\skills\browser-test\SKILL.md` | `$browser-test <task>` |
| Claude Code | `integrations/agents/claude/browser-test.md` | `C:\Users\hp\.claude\commands\browser-test.md` | `/browser-test <task>` |
| OpenCode | `integrations/agents/opencode/browser-test.md` | `C:\Users\hp\.config\opencode\commands\browser-test.md` | `/browser-test <task>` |

Copy the corresponding template contents exactly when installing or updating. Restart a host only if its own command/skill discovery cache does not refresh automatically.

## Removal / rollback

Remove only the three discovery files listed above (and the empty Codex `browser-test` directory, if desired). Do not change PATH, global environment variables, browser profiles, or managed state. Do not delete `D:\tools\chrome-agent-data`; use the wrapper's explicit `cleanup` operation only after reviewing its result.

To revert the integration source itself, revert its focused Git commits in this fork; the previous Windows-hardening commits remain intact.
