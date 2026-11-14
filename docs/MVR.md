# MVR (My Virtual Rig) — export, import, inspect

MVR is the exchange format a lighting/rigging plot leaves the building in. On
Vectorworks 2027 it has **no scriptable surface at all**, so this layer is split
in two: a GUI driver for the commands, and a pure-Python reader for the file.

| Tool | What it does | Verified |
|---|---|---|
| `export_mvr(path)` | File ▸ Export ▸ Export MVR…, answers the options dialog, types the name, saves, **moves the file to `path`**, verifies it | live, 130 676 bytes |
| `inspect_mvr(path)` | reads the ZIP + XML: provider, MVR version, layers, objects, meshes, GDTF specs | live + synthetic fixtures |
| `mvr_dialog()` | reports any MVR dialog on screen, for handing the flow to a GUI agent | live |
| `import_mvr(path)` | File ▸ Import ▸ Import MVR…, picks the file, reports VW's verdict | live, **refuses** (see below) |

## Why it is not a `vs.*` verb

The SDK index has **zero** GDTF/MVR functions on VW2027, and

```python
vs.DoMenuTextByName('Export MVR', 0)
```

raises a Vectorworks **script error** ("A Script error has occurred") instead of
running the command — the menu item is not scriptable, like the other export
commands. Every spelling was tried (`'Export MVR'`, `'Export MVR...'`,
`'ExportMVR'`, the Unicode ellipsis); all four produce the same error dialog.

So the tools drive the menu the way a person does, with **real input**
(`keybd_event`, `mouse_event`). Posted messages do nothing: VW's BCG widgets
hit-test the physical cursor and read the live keyboard state.

## How the menu is found

VW draws its menus with MFC/BCG, so a menu is an **untitled `Afx:` popup
window**, not a `#32768` Win32 menu — `GetMenu`/`GetMenuString` return nothing,
which is why the route is counted arrow presses instead of a name lookup:

```
Alt+F → 22×Down (Export) → Right → 6×Down (Export MVR…) → Enter
```

Each step is verified (a popup must appear, then a second one for the submenu)
and the resulting dialog is checked by **title** — a reordered menu fails loudly
instead of exporting something else. The item numbers live in `vwx_gui.py` with
the full menu listing in a comment.

## The dialogs

Export has an options dialog, import does not:

| Step | Export | Import |
|---|---|---|
| 1 | `Export MVR File` — settings (all objects / selected / visible, GDTF sync, mesh quality) → **OK** | `Open File` — straight to the file picker |
| 2 | `Save File` — name → **Save** | — |

`Export MVR File` is a plain `#32770`, so the existing `vw_dialog` /
`vw_dialog_press` tools read and press it like any other VW dialog.

## Two things the file dialog does not allow

**A path cannot be typed into the name field.** VW2027 turns `:` and `\` into
`ß`: typing `C:\Users\maxim\…\show.mvr` produced a file literally named
`ßUsersßmaximß…ßshow.mvr` on the Desktop (reproduced with both real keystrokes
and `WM_SETTEXT`). So `export_mvr` types only the **file name**, finds what VW
wrote, and moves it to the requested path — the result says `saved_to` and
`moved` so nothing is hidden.

**The Open dialog ignores typed input from outside the process.** The name field
stays empty however the keys are sent (foreground, focused, `WM_SETTEXT`, real
keystrokes — all verified), while the Save dialog accepts the same input. So
`import_mvr` picks the file from the dialog's **current folder**; put the file
there, or finish the dialog by hand or with a GUI agent (`mvr_dialog` reports
what is on screen).

## What the MVR actually contains

`inspect_mvr` reads the container without Vectorworks — an MVR is a ZIP with
`GeneralSceneDescription.xml` plus one `.glb` per object:

```
export-test.mvr: MVR 1.6 from Vectorworks 32.1.1.888839 — 3 layer(s),
42 scene object(s), 0 fixture(s), 19 mesh(es), 130675 bytes
```

Layer names (Schematic / Rack Elevation / 3D Layout), object element names and
GDTF specs come back as data, so a schema change shows up as a number instead of
a silent zero. That is also how the next finding was made.

## Import of a ConnectCAD-only MVR is refused

Round-tripping the export above gives:

> **Vectorworks could not find any data to load from the specified MVR file.**

The file is valid (MVR 1.6, 42 `SceneObject`s, 3 trusses/hoist among them), so
VW2027's MVR **importer** consumes fixtures — and this document has none. The
tool reports the message verbatim and `ok: false` rather than claiming success;
`import_mvr` also counts the document's objects before and after, because a
dialog that closes without importing looks exactly like a good import.

Not yet tested: an MVR that contains real lighting fixtures. That needs a plot
with Lighting Devices, and it is the first thing to try when one is available.

## Platform

Windows only (`mcp-server/vwx_gui.py`). On macOS every entry point raises
`GuiUnavailable` with a message saying so — there is no Mac driver yet, and a
tool that silently does nothing is worse than one that refuses.
