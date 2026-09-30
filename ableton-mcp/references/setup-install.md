# AbletonMCP — one-time setup

Read this only when installing or re-installing the AbletonMCP connection.

## What you're installing (two halves)

Both halves must run and **must come from the same source/version** (a mismatched Remote
Script and server can fail to talk):

1. **A Remote Script inside Ableton** ("AbletonMCP" control surface) — opens a **TCP
   socket on port 9877** that Live listens on. *Most setup failures are a forgotten,
   mis-named, or unselected Remote Script.*
2. **The MCP server** (`ableton-mcp`, Python) — your MCP client (Claude Code, Claude
   Desktop, Cursor) launches it; it relays commands to the Remote Script.

```
Claude  <->  MCP server (Python)  <->  Ableton Remote Script  <->  Live (LOM)
                            port 9877 TCP
```

Repo: **<https://github.com/jpoindexter/ableton-mcp>** (v2.0.0, 128 tools) — the fork this
skill documents. The original <https://github.com/ahujasid/ableton-mcp> (also what
`uvx ableton-mcp` fetches from PyPI) has ~37 tools and lacks `health_check`,
`remove_notes`, the `humanize_*`/`generate_*` helpers and `get_scale_notes`, so most of the
tool map in the skill fails on it. It has since gained arrangement tools
(`duplicate_to_arrangement`, `get_arrangement_clips`) — worth re-checking before assuming
a limit in the skill still applies there.

## Prerequisites

- Ableton Live 10+ (any edition; Pedal/Amp devices are Suite-only)
- A working MCP client (Claude Desktop / Claude Code / Cursor)
- Python 3.8+, git (or download repo ZIP)
- [uv](https://astral.sh/uv): macOS `brew install uv`; Windows `pip install uv`

## 1. Install the Remote Script (the step people miss)

0. `git clone https://github.com/jpoindexter/ableton-mcp.git` — the script is
   `AbletonMCP_Remote_Script/__init__.py`. Server and Remote Script come from this one
   checkout, so they always match. For `ableton-song-remix`, apply
   `remote-script-remix.patch` to the checkout now (see `remote-script-patch.md`).
1. Locate Live's MIDI Remote Scripts folder:
   - **macOS:** right-click Ableton Live → Show Package Contents →
     `Contents/App-Resources/MIDI Remote Scripts/` — or
     `~/Library/Preferences/Ableton/Live XX/User Remote Scripts`
     (Live 11+ also accepts `~/Music/Ableton/User Library/Remote Scripts/`)
   - **Windows:** `C:\Users\[You]\AppData\Roaming\Ableton\Live x.x.x\Preferences\User Remote Scripts`
     — or `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\`
2. Create a folder named **exactly `AbletonMCP`** (case-sensitive) and put `__init__.py`
   inside.
3. **Restart Ableton Live** — it scans Remote Scripts only at launch.
4. Settings → Link, Tempo & MIDI → free Control Surface dropdown → **"AbletonMCP"**;
   set that row's Input and Output to **None**.

## 2. Configure the MCP client

**Claude Code** — `.mcp.json` at project root (merge into existing `mcpServers`), running
the server from the same checkout as the Remote Script:
```json
{ "mcpServers": {
    "ableton": { "type": "stdio", "command": "uvx",
                 "args": ["--from", "/path/to/ableton-mcp", "--with", "mcp[cli]==1.12.2",
                          "ableton-mcp"],
                 "env": {} }
} }
```

**Claude Desktop / Cursor** — merge into the MCP config
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):
```json
{ "mcpServers": { "AbletonMCP": { "command": "uvx",
    "args": ["--from", "/path/to/ableton-mcp", "--with", "mcp[cli]==1.12.2", "ableton-mcp"] } } }
```

Restart the client. Notes:
- `uvx` not on PATH → use its absolute path (e.g. `~/.local/bin/uvx`).
- Don't use bare `"args": ["ableton-mcp"]` — that installs the PyPI package (the original
  37-tool server), which won't match the fork's Remote Script.
- **MCP SDK version.** The fork as published runs unchanged up to `mcp[cli]==1.12.2`
  (tested: all 128 tools, protocol 2025-06-18, live calls OK). 1.12.3–1.30 fail with
  `FastMCP.__init__() got an unexpected keyword argument 'description'`; 2.x renamed FastMCP
  to MCPServer and runs tool calls concurrently. A small patch to `MCP_Server/server.py`
  runs it on the **latest 1.x (1.30.0, tested live)**: import `MCPServer as FastMCP` when
  available (else `FastMCP`), pass `instructions=` instead of `description=`, and hold a
  lock around `send_command` so concurrent calls don't interleave on the socket. SDK 2.x
  still fails with that patch — not supported yet.
- **If you patch the server locally, don't run it with `uvx --from <folder>`.** uv caches a
  built environment for a local folder and keeps running it after the code changes (even
  `--reinstall-package` reused the old build). Install it editable in its own venv and
  point the client at the binary — edits are live, startup is fast and offline:
  ```bash
  uv venv --python 3.12 .venv-ableton-mcp
  uv pip install --python .venv-ableton-mcp/bin/python -e /path/to/ableton-mcp "mcp[cli]==1.30.0"
  ```
  ```json
  "ableton": { "type": "stdio", "command": "/path/to/.venv-ableton-mcp/bin/ableton-mcp", "args": [] }
  ```
- Keep API keys for other servers out of `.mcp.json` literals — reference an environment
  variable instead, since the file often ends up committed.

## 3. Verify

A **Set** is a Live project (`.als`); the start screen is not a Set.

1. File → New Live Set; bring Live to the foreground.
2. Run `health_check` (Claude Code: `ToolSearch select:mcp__ableton__health_check` first).
3. Success = a real response, e.g. `get_session_info` → `{"tempo": 120.0, "track_count": 2, …}`.
4. Smoke-test write access: `create_midi_track` → `get_session_info` shows track count +1.

To avoid a permission prompt on every call in Claude Code, add to `.claude/settings.json`:
```json
{ "permissions": { "allow": ["mcp__ableton__*"] } }
```
