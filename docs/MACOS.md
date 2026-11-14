# Picking this up on a Mac

Everything in this fork was built and verified on **Windows** against
Vectorworks Spotlight 2027 (32.1.1). This file is the handoff: what already
works on macOS unchanged, what is Windows-only and where it lives, and the
tests that decide whether a port is done.

Nothing here has been executed on a Mac. Treat every "should work" as a
hypothesis, not a fact.

---

## 1. Already portable — no work needed

The whole fork layer is plain `vs.*` Python and plain MCP wrappers:

| File | Why it is portable |
|---|---|
| `vwx-plugin/commands_spotlight.py` | only `vs.*` calls, no OS APIs |
| `vwx-plugin/commands_connectcad.py` | same |
| `vwx-plugin/commands_braceworks.py` | same |
| `vwx-plugin/vwx_verbs.py` | a tuple of module names |
| `mcp-server/spotlight_tools.py`, `connectcad_tools.py`, `braceworks_tools.py`, `mvr_tools.py` | `cmd(...)` wrappers only |
| `mcp-server/mvr_file.py` | pure `zipfile` + `ElementTree` — works anywhere |
| `tests/` | fake `vs`, no OS dependencies (except the two platform-guard tests, which skip on Mac) |

The verbs themselves are the valuable part and they are OS-agnostic. If the
transport works, the Spotlight/ConnectCAD/Braceworks surface works.

---

## 2. Windows-only, with what the Mac version needs

### `mcp-server/vwx_mcp_server.py` (vendored — keep the diff small)

| Function | Today | Mac needs |
|---|---|---|
| `vw_versions()` | reads `%APPDATA%\Nemetschek\Vectorworks\<ver>` | `~/Library/Application Support/Vectorworks/<ver>` (verify the real path on the Mac) |
| `_plugin_dir()` | same root + `Plug-ins\VW-MCP` | same root + `Plug-ins/VW-MCP` |
| `screenshot()` + `_screenshot_front()` | Win32 `PrintWindow`/`BitBlt` via ctypes | **M3**: `screencapture -x -l <windowid>` or `CGWindowListCreateImage`; window id via Quartz |
| `_open_dialogs()`, `vw_dialog()`, `vw_dialog_press()` | `EnumWindows` + `#32770` | **M4**: Accessibility API (`AXUIElement`) or AppleScript `System Events` — VW dialogs are NSWindows, not `#32770` |
| `_vw_windows()` | `EnumWindows` + class `Afx:` | NSWindow enumeration via Quartz (`CGWindowListCopyWindowInfo`) |

Each of those is guarded with `sys.platform != "win32"` today, so the failure
is honest ("only on Windows") rather than a crash — that is the state to
replace, one function at a time.

### `mcp-server/vwx_gui.py` (the MVR driver, Windows-only)

Drives VW's menu with `keybd_event` and reads dialogs with `EnumChildWindows`.
On macOS the equivalents are `CGEventPost` for input and the Accessibility API
for the file dialog, or AppleScript `tell application "System Events"`. Every
entry point already raises `GuiUnavailable` on non-Windows, and the MCP tools
report that message, so MVR currently answers "Windows-only" on a Mac —
acceptable, not silent.

### `bridge/` (all Windows)

| File | Purpose | Mac equivalent |
|---|---|---|
| `install_user_plugin.ps1` | copies the plug-in into the user Plug-ins dir | `install_user_plugin.sh` (does not exist yet) |
| `patch_workspace.py` | adds the menu command to `Spotlight.vww`, allocates a `ResourceManagerID`, sets `defaultWorkspace` | the XML logic is portable; only the `APPDATA` path lookup is Windows (it refuses with "this script is Windows-only") |
| `wake_watch.py` | palette-less trigger: heartbeat + `Ctrl+Shift+B` via `keybd_event` | needs `CGEventPost`; or use the `tcp` transport and skip it |
| `gui_click/gui_keys/gui_type/gui_drag/gui_rect.ps1` | real-input helpers for VW's BCG widgets | not needed: on macOS `CGEventPost` is the native path |
| `vwx-mcp.bat` | launcher with the env vars | a `.command`/`.sh` launcher |

### Transport

`mcp-server/vwx_mcp_server.py:103`:

```python
VWX_TRANSPORT = os.environ.get('VWX_TRANSPORT',
                               'file' if sys.platform == 'win32' else 'tcp').lower()
```

On a Mac the default is **`tcp`** — upstream's classic dialog-pump bridge on
`:9878`, where the VW-side plug-in opens a modal dialog and pumps commands. It
is the only transport that has ever been described as working on macOS, but it
has **not been run by this fork**. The `file` transport (job/result files +
menu-command trigger) is what all the Windows verification used; it needs a
trigger, which on macOS is the missing piece (`wake_watch` equivalent).

---

## 3. Acceptance tests, in the order they unblock things

Run from the repo root; `uv` is assumed.

```bash
# 0. offline — must stay green on any OS (94 tests)
uv run --with pytest --with fastmcp==4.0.10 --with pillow pytest tests -q

# 1. transport: is the bridge alive at all?
#    (server: MCP_TRANSPORT=streamable-http FASTMCP_PORT=8082
#     uv run --with fastmcp==4.0.10 python mcp-server/vwx_mcp_server.py)
uv run --with fastmcp==4.0.10 python tests/live_client.py ping

# 2. the fork surface (this is the real milestone)
uv run --with fastmcp==4.0.10 python tests/live_client.py \
    get_spotlight_devices get_spotlight_patch get_connectcad_devices \
    get_braceworks_hoists inspect_mvr

# 3. writes + revert (destructive — use a scratch document)
#    set_spotlight_patch -> revert_last -> both must report ok:true
```

Expected on a working port: `ping` → `{"status":"ok"}`, the Spotlight verbs
report `catalog: live` with `unresolved` empty, and `spotlight_worksheet`
returns `verified: true`.

---

## 4. Never executed on a Mac (verify, do not assume)

- `bridge/install_user_plugin.sh` — **does not exist**; the PowerShell script
  has never been ported.
- `MacTrigger` — the trigger abstraction exists in the design but has only ever
  run as a fake `subprocess` in tests.
- The `tcp` transport end-to-end from this fork.
- `patch_workspace.py` against a macOS `Spotlight.vww` (the XML logic is
  portable; the path lookup is not).
- Any `vs.*` call in `commands_spotlight.py` / `commands_connectcad.py` /
  `commands_braceworks.py` on macOS. The verbs are OS-agnostic, but the
  *field names* they read were verified against a Windows install — a localized
  Mac install could differ, which is exactly why every verb reports
  `unresolved` instead of blanking a field.

---

## 5. Suggested order

1. **Transport first.** Nothing else is testable without it. Try the `tcp`
   default; if the dialog-pump bridge works, `ping` answers and step 2 of the
   acceptance tests is meaningful.
2. **`_plugin_dir()` / `vw_versions()`** — 10 lines, unblocks the file
   transport and the plug-in install.
3. **M3 `screenshot`** — the one thing Windows cannot do for you, and the tool
   that catches geometry that reports `ok` but looks wrong.
4. **M4 `vw_dialog` / `vw_dialog_press`** — modal recovery; without it a single
   VW dialog blocks every tool until a human clicks it.
5. **MVR GUI driver** (`vwx_gui.py`) — lowest value per hour; MVR export can
   wait, and `inspect_mvr` already works on a Mac today.
