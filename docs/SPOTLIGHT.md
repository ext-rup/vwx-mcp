# Spotlight layer — reading a lighting plot

The fork's reason to exist: Vectorworks **Spotlight** data (Lighting Devices,
their patch, focus, colour, gobo and accessories) readable over MCP, on Windows
and macOS alike.

Everything here lives in **`vwx-plugin/commands_spotlight.py`** (MCP wrappers:
`mcp-server/spotlight_tools.py`), not in
`commands.py`. `commands.py` is a vendored upstream file and stays rebaseable;
the pump's `_dispatch` falls back to `commands_spotlight` when a verb is not in
`commands.py`, and `list_commands` merges both so discovery stays one call.

## Verbs

| Tool | Verb | Returns |
|---|---|---|
| `find_objects` | `find_objects` | UUIDs + count for **any** VW criteria string (the generic entry point) |
| `get_spotlight_devices` | `get_spotlight_devices` | every Lighting Device with patch/focus fields; `raw:true` for all record fields |
| `get_spotlight_device` | `get_spotlight_device` | one device: mapped fields, raw fields, cells, accessories |
| `get_spotlight_patch` | `get_spotlight_patch` | patch sheet rows **plus** conflicts (duplicate channel, duplicate/overlapping DMX address, unpatchable devices) |
| `get_spotlight_positions` | `get_spotlight_positions` | devices grouped by hanging position, with counts |
| `get_spotlight_focus` | `get_spotlight_focus` | devices grouped by focus, with colour/gobo/pan/tilt per device |
| `get_spotlight_accessories` | `get_spotlight_accessories` | per-cell accessory inventory with 2D/3D placement |
| `get_spotlight_params` | `get_spotlight_params` | the parameter catalog (`live:true` re-reads it from the document) |
| `dump_spotlight_params` | `dump_spotlight_params` | enumerates the catalog from the document and writes `spotlight_params.json` |

All of them accept a raw VW `criteria` string, so they compose with the rest of
the toolset: `"(PON='Lighting Device') AND (L='Rigging')"`, `"C='Rigging'"`,
`"SEL=TRUE"`.

## Why the code is data-driven

A Lighting Device is a plug-in object; its parameters are addressed by
**universal (worksheet) name**, not index:

```python
vs.LDevice_GetParamStr(h, cellIndex, accessoryIndex, 'channel')
#                        0 = first cell   -1 = the device itself, >=0 = accessory
```

Nobody publishes that name list, and it is **not** the localized field label in
the Object Info palette. A wrong name does not raise — it returns `''`. That is
exactly the silent-failure class this repo's `AGENTS.md` warns about, so:

1. `dump_spotlight_params` enumerates the real catalog from a live document
   (`vs.GetParametricRecord` + `NumFields`/`GetFldName`/`GetFldType`) and writes
   `vwx-plugin/spotlight_params.json`.
2. Each read verb resolves its logical keys (`channel`, `universe`, `address`,
   `position`, `focus`, `color`, `gobo`, …) through `_SYNONYMS` against the
   names **the object itself reports** (`_keys_for` → live wins), then the
   catalog file, then `_FALLBACK_KEYS`.
3. Anything that could not be resolved is returned in `unresolved` — an empty
   field and a field that does not exist must never look the same.
4. Every result carries `catalog: live | catalog | fallback`. `fallback` means
   "best-effort names, not verified" and adds a `warning`.
5. `raw: true` dumps every field the object actually has, so a wrong mapping
   still lets the caller read the data.

Free-text fields are parsed tolerantly: a designer may type `U1/001` into
address or leave universe empty, so `_universe_address` accepts `1`, `U1`,
`001`, `U1/001` and reports `universe_num`/`address_num` alongside the raw text.

## Verification status

**Offline (green, no Vectorworks needed)** — `tests/test_spotlight.py`, 18 tests
against a fake `vs` module: key resolution (live beats catalog beats fallback),
unresolved reporting, patch conflict detection (duplicate channel, duplicate
address, footprint overlap, missing values), tolerant universe/address parsing,
criteria pass-through, catalog write/read round-trip, the accessory walk, plus
three regressions from the first live run (junk field name skipped, popup field
falls back to the record, the verified field-type codes).

`tests/test_vs_arity.py` covers `vwx-plugin/*.py` by glob, so every `vs.*` call
in `commands_spotlight.py` is checked against `vs_index.json` for existence and
argument count — a wrong arity pops a modal dialog inside VW instead of raising.

**Verified live on Vectorworks Spotlight 2027 (32.1.1), 2026-11-14** — one
Lighting Device placed with `vs.CreateCustomObject('Lighting Device', p, 0)`:

| Question | Answer |
|---|---|
| Lighting Device type code | **86** (`vs.GetTypeN`) ✔ |
| Parametric record name | `Lighting Device`, **150** readable fields |
| Criteria `(PON='Lighting Device')` | matches ✔ (`strategy: criteria`) |
| `LDevice_GetCellCount` / `GetAccCount(h, 0)` | 1 / 0 on a bare device ✔ |
| Universal names | plain English: `Channel`, `DMX Address`, `Universe`, `Position`, `Focus`, `Color`, `Gobo Data`, `Accessory Inventory`, `Num Channels`, `Lightwright ID`, … |
| Key resolution | **27/27** logical keys resolved, 0 unresolved |
| `catalog` | `live` on every read verb |

Three findings that are now coded in, each of which cost a Vectorworks crash or
a silently empty field:

1. **`vs.GetFldType` does not return 0..3.** A real device reports 1 = long,
   2 = bool, 3 = real, 4 = text (plus 7/8/10/11/14/20/30 for coordinates,
   popups, control points, angles, symbol definitions). The old mapping read
   every text field with the wrong reader and got `''` back.
2. **Field 0 of the record has no usable name** (private-use code points,
   `GetFldType` = -23248). Passing that name to `LDevice_GetParamStr` **kills
   the Vectorworks process** — no dialog, no exception, the app is gone. Hence
   `_valid_name()`: a name that is not printable ASCII is never passed to a
   `LDevice_*` call.
3. **Popup / control-point / coordinate fields have no `LDevice_*` reader.**
   `LDevice_GetParamStr` returns `''` for `Device Type`, `System`, `Pan`,
   `Tilt`, … while the record holds the display value (`Light`, `A`, `0°`).
   `_read_param` therefore falls back to `vs.GetRField`, and the catalog's
   sample values are read that way from the start (`_sample_value`).
4. **The patch lives in `UniverseAddress`, not in `Universe`/`DMX Address`.**
   At device level the *record* is authoritative: `SetRField(h, rec,
   'UniverseAddress', '2/201')` sticks, while `Universe` and `DMX Address` stay
   empty (they are not derived from it), and `LDevice_GetParamStr` returns the
   old value until the next reset. `0/0` is Vectorworks' "not patched"
   sentinel and is reported as `address_num: null`, not as address 0. Writes
   therefore go through `SetRField` — `LDevice_SetParamStr` did not change the
   record in the same test.

Read priority in `_read_param`, in one line: **record first at device level
(`cell` 0, `acc` -1), `LDevice_*` first for a specific cell/accessory**, record
as the fallback in both cases.

Still unverified: `LDevice_GetAccPos2D/3D` (no accessory was attached), and the
criteria string on a *localized* install (the fallback document scan covers a
miss and reports `strategy: scan`).

## Generating the catalog

1. Open a plot (or place one Lighting Device) in Vectorworks.
2. `dump_spotlight_params` → writes `spotlight_params.json` next to the plug-in
   files (copy it to `vwx-plugin/` to ship it).
3. `get_spotlight_params` returns the catalog. `unresolved_keys` is empty for
   VW2027 as of 2026-11-14; a non-empty list means `_SYNONYMS` needs the name
   the dump printed.

Without the file every verb still works and says `catalog: fallback`.

## Getting a job into Vectorworks (the trigger)

A job file alone does nothing: something has to run the `VWX Bridge Start`
Python menu command, which is the only context where document mutation is safe.

Two triggers exist:

| Trigger | Needs | Notes |
|---|---|---|
| Native palette (`BraceWorxsVwxPlg.vlb`) | `bridge/deploy_native_bridge.bat`, VW closed, UAC | the production path; writes `ipc/native.alive` and posts the command without stealing focus |
| `bridge/wake_watch.py` | nothing but Python | dev/fallback path: keeps the heartbeat fresh and fires Ctrl+Shift+B with real key input, so it briefly focuses Vectorworks |

The menu command itself must be in the workspace. `bridge/patch_workspace.py`
adds it to the user copy of the workspace and points the `defaultWorkspace`
preference at that copy — both steps are required, and a plug-in command needs
a real `ResourceManagerID` (VW drops it silently at 0).

## Live verification recipe

```
ping                                   # bridge alive
get_spotlight_devices  {"limit": 5}    # catalog: live, one row per device
dump_spotlight_params  {}              # 150 fields, 27 keys, 0 unresolved
get_spotlight_patch    {}              # conflicts block
```

The patch sheet is the acceptance test: it must match the plot's own patch
report for the same devices.

## Writes (M2) — journaled, verified, revertable

Three verbs, all in `commands_spotlight.py`:

| Verb | Does |
|---|---|
| `set_spotlight_patch` | write patch/focus fields on a selection — `fields` for a bulk edit, `assignments` for per-device values, `dry_run` to look first |
| `renumber_spotlight` | sequential channels + DMX addresses, stepping by each fixture's footprint and rolling into the next universe when one would not fit |
| `revert_last` | replay the newest batch backwards (or a named `batch_id`) |

**Every write goes through one function**, `_apply`, which does three things in
order: read the current value, write + `ResetObject`, **read back**. A
`SetRField` that silently no-ops is the failure mode this whole file exists to
avoid, so the read-back is not optional and a mismatch comes back as
`ok: false` with `readback` showing what the object actually holds.

**The journal** (`spotlight_journal.json`, next to the plug-in files, last 20
batches) records `object_id`, `record`, `field`, `before`, `after`, `readback`
per field. `revert_last` refuses in three cases, each of which would otherwise
corrupt a plot quietly:

- the batch belongs to **another document** (UUIDs are per file — restoring
  would address nothing, or worse, something else);
- the batch was **already reverted** (a second revert would re-apply it);
- a field already holds its `before` value — someone undid it by hand, so it is
  skipped and listed in `already_before` instead of being written again.

If the journal cannot be written the result carries a `warning` that the change
is **not** revertable — better a loud write than a silent one-way edit. A `None`
value is refused outright (writing it would store the literal text `"None"` in
the record), and `revert_last` refuses to restore an entry that had no before
value, for the same reason.

Verified live on VW2027, 2026-11-14 (two devices):

```
set_spotlight_patch {fields:{channel:301, universe_address:3/301, position:Ladder}}
  → ok:true written:6, every field read back 301 / 3/301 / Ladder
get_spotlight_patch → 301 3/301 Ladder (both devices)
revert_last         → ok:true restored:6 failed:0 → 101 1/101 FOH, "" 0/0 ""
revert_last         → "No batch to revert"
renumber_spotlight {start_address:511} → 1/511, 1/512 (footprint 1)
revert_last         → restored:4
```

Writes use `SetRField`; `LDevice_SetParamStr` did **not** change the record in
the same test, so it is not the write path.

## Paperwork (M5) — worksheets that prove themselves

Two verbs:

| Verb | Does |
|---|---|
| `get_spotlight_report` | the rows as JSON — no document change, printable/diffable |
| `spotlight_worksheet` | builds a real Vectorworks database worksheet, then **reads it back** |

Five kinds, one definition table (`_REPORTS`): `channel_hookup`,
`instrument_schedule`, `patch_sheet`, `focus_chart`, `weight_report`.

**The column formulas are generated from the live record.** `spotlight_worksheet`
resolves each logical key through `_keys_for(hs)` and writes
`='Lighting Device'.'Channel'` — the name the object itself reports. A hardcoded
name would produce an empty column on a localized build, which looks exactly
like an empty plot.

**Verification is the feature.** After `RecalculateWS` the verb reads every
subrow cell and compares the per-column value multiset with the same data the
JSON report returns:

```
spotlight_worksheet {kind: channel_hookup, name: "Hookup Live"}
  → subrows 2, columns 10, verified: true
     Ch channel ok filled 2 | Dim dimmer ok filled 0 | U/A universe_address ok filled 2 | ...
```

`verified: false` comes with `detail[]` naming the column, what was expected and
what the sheet actually holds, plus a `warning`. A sheet that silently shows
nothing is the failure this whole file exists to prevent; only a read-back
catches it (VW's first `RecalculateWS` on a fresh database row can leave it
empty, so the verb retries once before reporting).

Weight and power are stored as localized text (`"7,5 kg"`, `"750 W"`), so
`_measure()` pulls the number out (comma decimals included) and `weight_report`
adds `weight_kg` / `power_w` per device plus `by_position` totals — the number a
rigger asks for first.

Verified live on VW2027, 2026-11-14 (two devices, one FOH one Ladder):
`channel_hookup` → 10/10 columns verified; `weight_report` → placed on the
drawing, 2 subrows, verified; duplicate worksheet name refused; `focus_chart`
sorted by position, verified.

## Still open

- `LDevice_GetAccPos2D/3D` (no accessory attached yet).
- Accessory *writes* (a device's accessories are cells, not record fields).
- The native palette (`deploy_native_bridge.bat`) is untested; `wake_watch.py`
  is the trigger that has actually run.
