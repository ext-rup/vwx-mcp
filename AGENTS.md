# AGENTS.md — integrating with vwx-mcp

Guide for agents (and humans writing them) driving Vectorworks 2026 through this
server. Read this before generating `vs.*` code or wrapping new tools — the
VW2026 API has sharp edges that produce **silent failures** (null UUIDs, no-op
draws) rather than errors.

## Connect

MCP endpoint: `http://127.0.0.1:8082/mcp` (streamable-http). The VW-side bridge
must be running first (see README). `ping` confirms the full chain is live.

## Working next to other agents (v14) — read this first

Several agents (and the user) can share one Vectorworks. The rules:

1. **Bind, don't switch.** Call `use_document("MyFile.vwx")` once (or pass
   `document=` on `vwx` / `vwx_batch` / `execute_script`). Every later call of
   your session runs in that document; the bridge activates and verifies it,
   and brings the user's document back afterwards. `switch_document` changes
   the front document for everyone — avoid it when others may be working.
2. **Unbound calls go to the user's document**, even while the bridge is
   visiting another file for someone else.
3. **Lock before multi-step builds:** `lock_document(doc, minutes, reason)` →
   other sessions get `DOC_LOCKED` on writes (reads pass). `unlock_document`
   when done.
4. **Batch work yields:** `use_document(doc, priority="batch")` lets
   interactive calls of other agents overtake your queue.
5. **Open/close without clicking:** `open_document(local_path)` (never from
   `Y:` — copy first), `close_document(doc, save=True)`.
6. **See who does what:** `get_bridge_status` (queue, bindings, locks, routing,
   audit tail).
7. `screenshot` always shows the FRONT document — with bindings that is not
   necessarily yours; check `get_bridge_status` → `routing`.

Error codes: `DOC_NOT_OPEN`, `DOC_AMBIGUOUS`, `DOC_SWITCH_FAILED`,
`DOC_LOCKED`, `DOC_UNSAVED`, `DOC_CLOSE_NEEDS_FORCE`, `DOC_OPEN_TIMEOUT`,
`PATH_DENIED` — none of them ran anything.

## Three access layers — pick the narrowest that works

1. **Explicit tools** (248). Typed, documented, safe. Prefer these.
2. **`vwx(command, params)`** — generic dispatcher to any verb in `commands.py`.
   Call `list_commands` to discover. Use when no explicit wrapper exists but a
   `commands.py` verb does.
3. **`execute_script(code)`** — arbitrary `vs.*` Python on the VW main thread.
   Last resort / one-offs. Contract:
   - `print(...)` → captured into the `output` field.
   - assign **`__result__`** → returned in `result` (str/int/float/list/dict/bool only).
   - There is **no** `return` and no `return_value` — assigning anything else is ignored.

## Object addressing — UUIDs only

Objects are identified by **UUID strings**: `vs.GetObjectUuid(handle)` /
`vs.GetObjectByUuid(uuid)`. The old `InternalIndex` APIs are **gone on VW2026** —
do not use them. Tool results return `object_id` = the UUID.

## Toolset presets

If the client is loading too many tools, set `VWX_TOOLSET` (env, in the launcher):
`full` | `gis` | `modeling` | `baumkataster` | `minimal`. Mapping lives in
`mcp-server/tool_tags.py`. Filtering uses the fastmcp Visibility API
(`mcp.enable(tags=…, only=True)`).

## VW2026 API gotchas (silent failures — memorize these)

| Symptom | Cause | Do this instead |
|---|---|---|
| `draw_circle` returns `object_id: null`, nothing drawn | `vs.ArcByCenter((cx,cy), r, 0, 360)` is broken on VW2026 | `vs.Oval(cx-r, cy+r, cx+r, cy-r)` (bbox: left, top, right, bottom), then `vs.LNewObj()` |
| Arc has wrong angular extent | `vs.Arc`'s 6th arg is the **sweep** (included) angle, **not** the end angle | `vs.Arc(l, t, r, b, start, sweep)` — pass sweep directly (verified: `GetArc` of `Arc(…,30,90)` → `(30, 90)`) |
| `vs.GetVWVersion` → AttributeError | does not exist on VW2026 | `vs.GetVersion()` → `(major, minor, maint, build)` |
| Can't enumerate class names | `GetClassName` / `GetClName` removed | `vs.ClassNum()` + `vs.ClassList(i)` (1-based) works on VW2026 |
| `vs.GetObject(name)` says a name exists that doesn't | returns a dummy handle of **type 0** for unknown names | treat as missing unless `vs.GetTypeN(h) != 0` (helper `_name_obj`) |
| A plug-in object "contains" hundreds of layer objects | `vs.FInGroup()` of an **empty** group returns a handle into the **parent list** (layer), so `ForEachObjectInList` walks the whole layer | count a child only if `GetObjectUuid(GetParent(child)) == container UUID` (see `_deep_count`) |
| `while h: h = vs.NextObj(h)` hangs VW | handle-walk loops can spin forever on VW2026 | `ForEachObject` with a criteria string, or `BuildResourceList` for resources |
| Drop shadow offset/blur 1000× too big after copying | `SetDropShadowData` stores offset/blur 1000× relative to `GetDropShadowData` | pass `offset/1000`, `blur/1000`, verify by read-back |
| Text position from `GetBBox` is metres off | `GetBBox` of rotated text is a screen box | `vs.HCenter(h)` / `vs.GetTextOrientation(h)` |
| `LNewObj()` returns the wrong/no object after a geometry op | some ops convert/replace (e.g. `DTM6_SendToSurface` converts 2D→3D and does **not** surface via `LNewObj`) | name the object first (`SetName`) + look it up, or use `PrevObj(LNewObj())` |
| `ForEachObject` callback corrupts iteration | mutating (delete/create/reclass/restack) during traversal invalidates `NextObj` | collect handles first, mutate after |
| `SetFillFore`/`SetPenFore` silently no-op | passing positional r,g,b | pass a single `RGBCOLOR` tuple |
| Old marker/pen/dash/wall-height calls misbehave | pre-2019 forms are obsolete | use the `…N` variants (`SetLSN`, `InsertNewComponentN`, …) |
| Criteria string matches nothing | quoting | single-quote record names, mind the parens: `"((R in ['Part Info']))"` |

## Resources (Zubehör) and plug-in styles — what a script can and cannot do

Verified live on VW2026 (Sept 2026). Commands: `resource_list`, `resource_info`,
`resource_import`, `resource_duplicate`, `plant_style_relink`, `pio_nesting_check`,
`datatag_refresh_all` (plus the older `resource_tree/move/rename/delete/create_folder`).

| Task | Works by script? | How |
|---|---|---|
| List resources of any type | yes | `BuildResourceList(type, 0, '')` / `BuildResourceListN(type, path)`; types 16 symbol/style, 18 worksheet, 19 material, 47 record, 66 hatch, 92 folder, 96 line type, 97 texture, 109 text style, 120 gradient |
| Duplicate a symbol or plug-in style (plant, data tag, …) | yes, via import | rename existing → import original from the **saved** file (`ImportResToCurFileN`) → rename import → rename back (`resource_duplicate`). Copies hidden style data and generated geometry (e.g. Maxon plant meshes). Unsaved edits are not included — save first |
| `CreateDuplicateObject(symbolDefinition, None)` | no | returns an invalid handle |
| Create a plug-in style from scratch | no | `BeginSym` + copied inner PIO + `SetSymDefSubType` yields a style **without** hidden data (data tags render no text). Create styles in the UI |
| Edit a data tag layout / field definition (`#Record#.#Field#`) | no | UI only; afterwards call `datatag_refresh_all` or new tags keep the placeholder |
| Link Plant objects to a plant style | yes | Plant fields `PlantDescription`, `Plant Name Formula` (`"<style>"`), `isCustom=False`, `ResetObject`; after editing the style's inner plant, reset instances **twice** (first regen still shows the old hidden symbol size) |
| Edit a plant style's size | yes | set the inner plant's `spread`/`height` (+ spacing fields) and `ResetObject` it; instances then draw at that size (2D and 3D) |
| Attach a Maxon/Laubwerk 3D plant | partly | the `lw_*` fields can be copied, but the proxy **mesh** is only generated by the UI. Set it once in one style, then `resource_duplicate` that style for other sizes and change spread/height — the mesh scales with the instance |
| Import: identical resource already present | skipped | documented behaviour: exact match is no conflict, callback not called, existing handle returned |
| Names | global | resources share one namespace with layers and objects (a layer named X blocks a style named X) |

## Terrain: grades, stakes, hardscape surface modifiers (verified 2026-10-10)

| Task | Command | Notes |
|---|---|---|
| Grade (Gefälle-Grundriss) on a layer | `create_grade` → `grade_finish` (separate call) | Needs ONE tool-placed Grade CW on the target layer (or `template`): a Grade made by `CreateCustomObjectPath` stays uninitialised (stub arrow at −10/−10, length 0). The template's height Data Tags only appear after the script ends — `grade_finish` moves the end tag and drops duplicates at network nodes |
| 3D polygon → grades | `convert_3dpoly_to_grades` (+ `hardscape` to put them into a hardscape) | one grade per edge; `GetPolyPt3D` is 0-based |
| Stake (Höhenpunkt) | `create_stake` | elevation = the object's 3D position; a reset rewrites `Z Value` from it |
| Grade INSIDE an aligned hardscape (shapes the surface without a site model) | `hardscape_prepare_modifiers` → `python tools/belag_modifikatoren_oeffnen.py` (once per hardscape, then `--verlassen`) → `hardscape_add_grade` | The modifier group exists only after the UI command "Oberflächenmodifikatoren bearbeiten" was entered once; groups built by script are discarded on reset. Aligned = `Config=Aligned` + `Mode 3D=7` + `Site Model Interaction=ActAsBoth` (`Mode 3D` alone leaves the menu item missing) |
| Read a hardscape surface | `hardscape_sample_z`, `hardscape_modifier_info` | `GetZatXY` on a hardscape returns 0 almost everywhere — the sampler triangulates a `MeshToGroup` copy instead |

Coordinate rules (all checked against the georeferenced Lageplan, origin −2047217/−6626760, hardscape rotated −13.9°):
- PIO paths are stored RAW: `raw = local − GetOrigin()`. A path written with `AddPoint(0,0)` starts at `+origin`, kilometres off in a georeferenced file. `_grade_shape` subtracts the origin.
- Inside a hardscape, modifiers live in its local raw frame: `v = R(−rz)·(world − offset) − GetOrigin()`; mesh and path use the same frame.
- Heights are absolute; the surface = grade height + the grade object's z → keep inner grades at z = 0.
- Changing the user origin afterwards does not disturb existing inner modifiers (re-sampled after `SetOrigin`).

## VW2026 API renames (function does not exist under the old name)

These raise `module 'vs' has no attribute …` (or wrong-arg engine errors). All
found + fixed via the full command sweep; the correct forms are in `commands.py`.

| Old / wrong | VW2026 correct | Notes |
|---|---|---|
| `vs.CreateExtrude(h, ht)` | `vs.HExtrude(h, zBottom, zTop)` | z baked into the extrude, no separate move |
| `vs.LinDimN(...)` | `vs.LinearDim(start, end, offset, dimType, arrow, textFlag, textOffset)` | 7 args |
| `vs.AngularDim(center, p1, p2, off, arr, txt)` | `vs.AngularDim(startPt, endPt, arcCenter, textOffset, arrow, textFlag, posAngle)` | 7 args; **center is 3rd** |
| `vs.SetClassVisibility(name, n)` | `vs.ShowClass(name)` / `vs.HideClass(name)` | by name |
| `vs.IFC_SetPSetAttribute(...)` | `vs.IFC_SetPsetProp(h, pset, prop, value)` | value is a STRING |
| `vs.ZoomToSel()` | `vs.DoMenuTextByName('Fit To Objects', 0)` | selection-aware fit |
| `vs.SetWSCellValue(ws, r, c, v)` | `vs.SetWSCellFormula(ws, r, c, r, c, v)` | 5 cell coords + value |
| `vs.SaveDocument()` | `vs.DoMenuTextByName('Save', 0)` | keeps path/format |
| `vs.SymbolCreate(...)` | `vs.BeginSym(name)` … create geometry … `vs.EndSym()` | captures objects made between the calls |
| `vs.HMirror(h, p1, p2)` | `vs.MirrorN(h, dup, p1, p2, preserveMatrix)` | dup=False transforms in place |
| `vs.SetLName(h, name)` | `vs.SetName(h, name)` | generic — renames any named object incl. layers |
| `vs.GetNumberOfComponents(h)` | returns **`(ok, count)`** tuple | unpack `[1]`, not an int |
| `create_wall` via `vs.SetPrefReal(85)`+`vs.SetPref(68)` | `vs.SetWallWidth` → `vs.Wall` → `vs.SetWallThickness` + `vs.SetWallHeights` | the pref-poking form **hard-crashes VW** |

**Verbs that always open a modal VW dialog** (the `vs` API has no headless path):
`export_pdf`, `export_image`, `export_dxf`, `export_shp`, `export_ifc`,
`save_document_as`, `import_dwg`, `import_image`. `export_pdf` in particular
calls `AcquireExportPDFSettingsAndLocation`, which *asks the user*. Expect a
dialog; automated runs skip these.

## Knowledge index — `vs_index.json` (author scripts right the first time)

`vwx-plugin/vs_index.json` (625 KB, built by `tools/build_vs_index.py` from the
SDK `vs.py` stub) maps all **3071** `vs.*` functions →
`{args, arity, required, ret, cat, doc}`. Deploy it next to `commands.py`.

Two verbs expose it (via the `vwx` dispatcher or as MCP tools):

- **`vs_signature`** — `{name}` returns the exact signature
  (`vs_signature('AngularDim')` → 7 args, names, category, doc); `{search}` /
  `{category}` searches. Use this **before** writing an `execute_script` body so
  you never guess an arg count and trip a VW engine-error dialog.
- **`vs_index_stats`** — index size + per-category counts (confirms deployment).

`commands.py` also loads the index at import and offers `vcheck(name, argc)` /
`vsig(name)` internally, so call sites can validate arity and return a clean
error dict instead of surfacing a modal Script-Fehler. Rebuild after an SDK
update: `python tools/build_vs_index.py <path-to-vs.py>`.

## SDK enrichment verbs (added from the index gap analysis)

New capability wrapped from untapped `vs.*` domains (all live-tested):

- **3D modeling**: `create_extrude_along_path` (sweep profile along path),
  `create_tapered_extrude` (draft-angle extrude), `create_loft` (skin NURBS
  through a group of section curves), `rotate_object_3d`, `draw_locus_3d`.
- **2D surfaces (paint-bucket booleans)**: `add_surface` (union),
  `clip_surface` (subtract), `intersect_surface`, `combine_into_surface`
  (polyline from a bounded region around a point), `add_hole`, `polygonize`,
  `draw_locus`.
- **Graphic calculation (pure math, no document change)**:
  `line_line_intersection`, `circle_circle_intersection`,
  `line_circle_intersection`, `three_point_center`, `polygon_area_at_point`.
  These return named point fields **plus** a `raw` field (the exact VS tuple);
  points are extracted generically, so they are robust to VS return-order quirks.
- **Introspection**: `get_3d_info` (bbox h/w/d), `get_centroid_3d`.

Surface booleans **consume** their inputs (VW replaces them with the result) —
re-fetch handles afterwards, don't reuse `object_id_a/b`.

Live-testing findings (all reproduced):

- **`create_loft` recipe**: the group must contain **NURBS curves**, not planar
  ovals/polys. `vs.ConvertToNURBS(h, keepOrig)` **returns** the new handle (does
  NOT advance `LNewObj`; arg 2 is keepOrig, not delete). Working pattern:
  `BeginGroup()` → per section: create curve → `nh = ConvertToNURBS(c, False)` →
  `Move3DObj(nh, 0, 0, z)` → `EndGroup()` → `LNewObj()` is the group. Loft of
  three circles at z=0/80/160 → type-84 solid, depth = z-span.
- **`create_extrude_along_path`**: profile and path must NOT be coplanar
  (degenerate sweep → nil). Use a 3D path (`BeginPoly3D`/`Add3DPt`) rising out
  of the profile plane; the verb returns a clear error for the coplanar case.
- **`vs.Centroid3D`** returns a FLATTENED `(ok, x, y, z)` 4-tuple on VW2026 —
  not `(ok, point)`. `get_centroid_3d` handles both.
- **`combine_into_surface` is quarantined** (no `@vtool`; `vwx` dispatch refuses
  without `force:true`): `vs.CombineIntoSurface` runs a document-wide region
  resolve on VW's main thread — measured **215 s frozen UI** on a small test doc
  before returning. Draw a closed polygon instead.

## SDK enrichment 2 — architecture, lights, criteria, worksheets, text, edit

36 more verbs (35/36 passed the live batch on first run — index-driven authoring):

- **Architecture**: `create_roof` (footprint edges + slope/eave, one call),
  `create_slab`, `join_walls` (T/L), `add_symbol_to_wall` (doors/windows),
  `set_wall_style`/`get_wall_style`.
- **Lights**: `create_light` (directional/point/spot), `set_light_info`,
  `get_light_info`.
- **Criteria engine (bulk power)**: `criteria_count`, `select_by_criteria`,
  `deselect_by_criteria`, `eval_expression` (AREA/PERIM/VOLUME/record fields
  on one object — the worksheet formula engine, headless).
- **Worksheets (deep)**: `get_worksheet_cell` (string + numeric),
  `get_worksheet_size`, `insert/delete_worksheet_rows`,
  `insert_worksheet_columns`, `set_worksheet_column_width`.
- **Text**: `get_text`, `set_text`, `set_text_size_all`.
- **Edit/convert**: `convert_to_polygon` (tessellate), `convert_to_polyline`
  (arcs kept), `set_stacking_order` (front/forward/backward/back),
  `move_object_3d`.
- **NURBS/solids**: `create_shell` (surface -> solid), `revolve_with_rail`
  (geometry-sensitive: degenerate setups error out cleanly), `offset_nurbs`,
  `extend_nurbs_curve`.
- **Layers/view/doc**: `set/get_layer_elevation` (Z + deltaZ),
  `set_view_angles` (flyover-style), `set_projection`, `get_object_metrics`
  (area+perimeter), `get_document_units`.

One more auto-dismiss signature learned: the VW compile/runtime error dialog
("Beim Kompilieren … Error Output anzeigen") appears when a `vs.*` call fails at
the ENGINE level (bad geometry args) — added to the native palette's dismiss
list (rebuild + redeploy `VwxBridge.vlb` to activate).

## SDK enrichment 3 — report worksheets, IFC deep, textures, doc defaults

30 more verbs, all live-tested (28 first-run; 2 IFC parse fixes below):

- **Report worksheets (the auto-report engine)**: `create_report_worksheet` —
  ONE call = worksheet + header + `=DATABASE(criteria)` row + column formulas +
  recalc + optional on-drawing placement. One subrow per matching object.
  Plus: `set_worksheet_database_row`, `get_worksheet_subrow_count/cell`,
  `get_worksheet_cell_formula`, cell alignment / text format / number format /
  fill / row height / merge, `place_worksheet_on_drawing`.
- **IFC deep**: `ifc_list_psets`, `ifc_get_pset_prop`, `ifc_attach_pset`,
  `ifc_remove_pset`, `ifc_define_pset` (custom schema), `ifc_get/set_entity_prop`,
  **`ifc_bulk_set_pset`** (criteria → entity + pset prop on every match; the
  DIN276 KG bulk classifier — verified 3/3 with read-back).
- **Textures**: `create_texture`, `get_texture_info`, `set_texture_size`,
  `set_object_texture` (by resource name via `Name2Index`), `get_object_texture`,
  `set/get_texture_mapping` (SetTexMapRealN selectors: 1=offsetX 2=offsetY
  3=rotation 4=scale2D). Read-back is meaningful on 3D objects.
- **Doc defaults**: `set_default_attributes` (RGB → `RGBToColorIndex`, values
  ×257 to 16-bit), `set_default_text_style` (font via `GetFontID`),
  `set_default_marker`.

IFC gotchas (verified live):
- `IFC_GetPsetProp`/`IFC_GetEntityProp` return **`(ok, value, ifcTypeCode)`** —
  value is index 1, NOT last.
- `IFC_SetPsetProp` returns False until the pset is **attached** to that object
  — attach + retry (both `set_ifc_property` and the bulk verb do this).
- Worksheet DATABASE binding: cell formula `=DATABASE((criteria))` on column 0
  of the row; subrows appear after `RecalculateWS`.

## SDK enrichment 4 — GIS coordinate engine + polygon vertex editing

11 more verbs (all live-tested; lat/lon round-trip exact):

- **GIS**: `geo_to_drawing` / `drawing_to_geo` (WGS84 ⇄ drawing via document
  georef — feed OSM/GPS straight in), `get_georeference_info` (origin,
  angle-to-north, projection), `get_projection` (WKT + Proj4),
  `set_document_georef` (EPSG, e.g. 25832).
- **Polygon vertex editing**: `get_poly_vertices`, `set_poly_vertex`,
  `insert_poly_vertex` (corner/bezier/cubic/arc), `delete_poly_vertex`,
  `set_poly_closed`, `get_poly_holes`.

Gotcha: the `…N` GIS functions return **`(ok, value…)`** tuples with a leading
boolean — `_nums()` in commands.py strips flags generically.

## Spotlight — reading a lighting plot (fork layer)

Twelve verbs in **`vwx-plugin/commands_spotlight.py`** (never in commands.py —
that file stays vendored/rebaseable; the pump's `_dispatch` falls back to this
module and `list_commands` merges both). Their MCP wrappers live in
**`mcp-server/spotlight_tools.py`**, imported by 4 lines at the end of
`vwx_mcp_server.py` (before `main()`, which blocks in `mcp.run()` — an import
after it never executes, and a plain `import vwx_mcp_server` from the wrapper
module would build a second FastMCP instance and answer "Unknown tool").
Full detail: `docs/SPOTLIGHT.md`.

| Tool | Purpose |
|---|---|
| `find_objects(criteria)` | UUIDs + count for any criteria string — the generic entry point |
| `get_spotlight_devices` | all Lighting Devices with patch/focus fields (`raw:true` = every record field) |
| `get_spotlight_device` | one device: fields, raw fields, cells, accessories |
| `get_spotlight_patch` | patch sheet **plus** conflicts: duplicate channel, duplicate/overlapping DMX address, unpatchable |
| `get_spotlight_positions` | devices grouped by hanging position |
| `get_spotlight_focus` | devices grouped by focus, with colour/gobo/pan/tilt |
| `get_spotlight_accessories` | per-cell accessory inventory + 2D/3D placement |
| `get_spotlight_params` / `dump_spotlight_params` | the parameter catalog (dump writes `spotlight_params.json`) |
| `set_spotlight_patch` | write patch/focus fields (`fields` bulk, `assignments` per device, `dry_run`) — journaled |
| `renumber_spotlight` | sequential channels + DMX, stepping by footprint, rolling universes — journaled |
| `revert_last` | undo the newest write batch from `spotlight_journal.json` |
| `get_spotlight_report` | paperwork rows as JSON (channel hookup, instrument schedule, patch, focus, weight) |
| `spotlight_worksheet` | builds a real VW database worksheet and **verifies it cell by cell** |

## ConnectCAD + Braceworks (M6) — `commands_connectcad.py`, `commands_braceworks.py`

Twelve read verbs; full detail in `docs/CONNECTCAD.md`.

| Tool | Purpose |
|---|---|
| `get_connectcad_devices` | devices with room/rack/U, power, weight, BTU |
| `get_connectcad_circuits` | circuits with full source->dest topology + length |
| `get_connectcad_cables` | cable paths: id, count, length, circuits, total |
| `get_connectcad_rooms` / `_racks` | rooms and racks **with what is in them** |
| `get_connectcad_signals` / `_connectors` | the `CC_Get*Data` catalogs |
| `get_connectcad_schedule` | equipment/circuit/cable/rack/room rows as JSON |
| `connectcad_worksheet` | database worksheet for a schedule, verified cell by cell |
| `get_braceworks_hoists` | hoists with capacity, point load, **overload flag** |
| `get_braceworks_trusses` | straight/curved trusses, length, distributed weight |
| `get_braceworks_loads` | per-origin totals: hoists, load, capacity, reaction force |

## MVR exchange (M6) — `mvr_tools.py` + `vwx_gui.py` + `mvr_file.py`

MVR has **no `vs.*` surface** on VW2027 (0 GDTF/MVR functions) and
`DoMenuTextByName('Export MVR', 0)` raises a VW script error, so these tools
drive the menu with real input. Detail in `docs/MVR.md`.

| Tool | Purpose |
|---|---|
| `export_mvr` | File > Export > Export MVR..., verified by the file on disk |
| `import_mvr` | File > Import > Import MVR..., reports VW's verdict + object count delta |
| `inspect_mvr` | reads the MVR ZIP/XML in pure Python (no VW): layers, objects, GDTF |
| `mvr_dialog` | what MVR dialog is on screen — for handing the flow to a GUI agent |

- **VW menus are untitled `Afx:` popups**, not `#32768` — `GetMenuString` finds
  nothing, so the route is counted arrow presses, verified by the dialog title.
- **A path cannot be typed into VW's file dialog**: `:` and backslash become
  the literal character `ß` (`C:\Users\...` -> `ßUsersß...`). Type the file
  NAME, then move the file to where the caller wants it.
- **The Open dialog ignores typed input** from outside the process (the Save
  dialog does not) — the file must be in the dialog's current folder.
- **VW2027 refuses an MVR with no fixtures**: round-tripping a ConnectCAD-only
  plot gives "could not find any data to load from the specified MVR file".

Findings that cost a crash or a silent zero (all coded in):

- **`CC_GetCircuitSource` / `CC_GetCircuitDest` hard-crash VW2027** — process
  death, no dialog, the pump never returns. Never call them; the `Src_*`/`Dst_*`
  record fields carry the same topology.
- **The hoist plug-in is `HoistVW`, not `Hoist`** — `'Hoist'` builds a legacy
  object with none of the load fields.
- **Braceworks stores mass twice**: a localized string (`'50,00 kg'`) and a raw
  number in the document's internal unit, which is **grams** on a metric
  document (`MaximumLoad = 50000`). The scale is derived from the pair the
  object reports (`mass_scale`), never assumed.
- **ConnectCAD numbers are localized text with exponents** (`'-1,2e01'`,
  `'4,826e02'`) — `float()` fails on both parts; use `_cnum`.
- **A worksheet database row binds in COLUMN 0**, not column 1. In column 1 the
  text is stored as a plain cell and recalculates to zero subrows — the exact
  look of an empty sheet.
- **A popup field renders its choice label** (`'VideoJack'` -> `'Video
  Jackfield'`), so `_verify_sheet` compares presence for `GetFldType == 8`.
- **MVR/GDTF have no `vs.*` surface at all** on VW2027 (0 functions); it is a
  menu command with a dialog, so it is deliberately not wrapped.

Lighting Device parameters are addressed by **universal (worksheet) name**, not
index: `vs.LDevice_GetParamStr(h, cell, accessory, 'channel')` — `cell` 0-based,
`accessory` **-1 = the device itself**, `>=0` = an attached accessory. A wrong
name returns `''` instead of raising, so the verbs resolve keys from the
object's own parametric record (`GetParametricRecord` + `NumFields`/`GetFldName`)
and report what they could not map in `unresolved`. Every result carries
`catalog: live | catalog | fallback`; `fallback` means unverified best-effort
names and adds a `warning`. `raw:true` is the escape hatch.

Patch fields are free text (`U1/001`, `001`, `1`), so `universe_num` /
`address_num` are parsed tolerantly and returned next to the raw text.

**Verified live on VW2027 Spotlight (32.1.1), 2026-11-14** — one device placed
with `vs.CreateCustomObject('Lighting Device', p, 0)`:

- type code **86**; parametric record `Lighting Device` with **150** fields;
- universal names are plain English (`Channel`, `DMX Address`, `Universe`,
  `Position`, `Focus`, `Color`, `Gobo Data`, `Accessory Inventory`,
  `Num Channels`, `Lightwright ID`, …) — 27/27 logical keys resolved;
- **`vs.GetFldType` is not 0..3**: 1 long, 2 bool, 3 real, 4 text (7/8/10/11/
  14/20/30 = coordinate, popup, control point, angle, symbol definition);
- **field 0 of the record has a junk name** (private-use chars, type -23248) and
  passing it to `LDevice_GetParamStr` **kills the Vectorworks process** — hence
  `_valid_name()`; never pass a non-printable name to a `LDevice_*` call;
- popup/control-point fields return `''` from `LDevice_GetParamStr`; the record
  holds the display value, so reads fall back to `vs.GetRField`;
- **the patch lives in `UniverseAddress`** (`"universe/address"`): `SetRField`
  into it sticks, `Universe`/`DMX Address` are not derived from it, and
  `LDevice_GetParamStr` lags a reset behind. `0/0` = not patched (reported as
  `address_num: null`). Device-level reads therefore prefer the record;
  cell/accessory reads prefer `LDevice_*`.

**Prerequisite for exact fields**: `dump_spotlight_params` against a document
that contains at least one Lighting Device → `spotlight_params.json` (a copy
lives in `vwx-plugin/`).

**Paperwork** (`spotlight_worksheet`) generates its column formulas from the
universal names the live record reports, then reads every subrow back and
compares it with the JSON report — `verified:false` plus a `detail[]` naming the
column, instead of a sheet that silently shows nothing. Weight/power are
localized text (`"7,5 kg"`), so `_measure()` parses the number and
`weight_report` adds per-device `weight_kg`/`power_w` and `by_position` totals.

**Writes** go through `_apply`: read before → `SetRField` + `ResetObject` →
**read back** (a mismatch is `ok:false` with the actual value, never a silent
success). `LDevice_SetParamStr` does not change the record — `SetRField` does.
The journal is per document, so `revert_last` refuses a batch from another file
and skips fields already restored by hand.

**Trigger** (a job file alone does nothing — something must run the menu
command): the native palette (`bridge/deploy_native_bridge.bat`, production) or
`bridge/wake_watch.py` (dev fallback: heartbeat + Ctrl+Shift+B with real key
input, briefly focuses VW). The menu command must be in the workspace:
`bridge/patch_workspace.py` adds it to the user copy **and** points the
`defaultWorkspace` preference there; a plug-in command with `ResourceManagerID`
0 is dropped silently, so the script allocates a real ID.
Without it the verbs still work and say `catalog: fallback`.

## Language: the client surface is English

Upstream was written against a German install, so `list_documents` answered
`{"aktiv": ..., "datei": ...}` and `vw_dialog_press` said "Knopf 'OK' nicht
gefunden". That is translated: keys, messages and docstrings are English.
German **data** names stay (`Höhe`, `LL-Erdbau`, `CGA_TG`, `LL_03_Bäume` — they
are real names in a German document). `tests/test_english_surface.py` enforces
the split; mapping table and the inline-comment remainder: `docs/ENGLISH.md`.

## macOS

Everything here was built on Windows. `docs/MACOS.md` is the handoff: what is
portable as-is (all the fork verbs — they are pure `vs.*`), what is Windows-only
and where (`_plugin_dir`, `vw_versions`, `screenshot`, `vw_dialog*`,
`vwx_gui.py`, `bridge/*`), and the acceptance tests to run before calling a port
done. The transport default differs: `file` on Windows, `tcp` on macOS.

## Server internals (for tool authors)

- **`@mcp.tool(output_schema=None)`**, never `structured_output=False`. The server
  runs **standalone fastmcp 3.x** (not the bundled `mcp.server.fastmcp`); the
  standalone has no `structured_output` kwarg, and emitting an `outputSchema`
  triggers a Claude Code bug that silently drops **all** tools. `output_schema=None`
  suppresses it.
- New tools are registered via the **`vtool`** wrapper (in `vwx_mcp_server.py`),
  which forwards to `mcp.tool(output_schema=None)` and injects the tool's tag from
  `tool_tags.py` by function name. Add the new tool name to `tool_tags.py` too
  (a probe asserts every tool is tagged — currently 248/248).
- Tags must be set at **registration** (decorator) for the Visibility API; mutating
  `tool.tags` afterward does not affect `enable/disable`.
- Tool bodies return a JSON **string** via `cmd(command_type, params)`; the actual
  `vs.*` work lives in `vwx-plugin/commands.py` (runs inside VW, hot-reloads per call).
- **VW keeps the Python interpreter alive across menu commands.** A module
  imported with `from X import Y` keeps the object bound at the first call of the
  session, so a redeployed `vwx_verbs.py` is ignored and the new module answers
  "Unknown command" while the file on disk looks right. Read such lists through
  the pump's `_get_module(name)` (mtime-reloading) or `importlib.reload` — never
  a bare `from X import Y`. The same trap applies to helpers imported across
  fork modules: look them up through the module at call time.

## Adding a tool — checklist

1. Implement the verb in a fork module (`vwx-plugin/commands_<area>.py`) — NOT in
   `commands.py`, which stays vendored and rebaseable. Mind the gotchas above.
2. Add the module to `vwx-plugin/vwx_verbs.py` (`MODULES`) — that one tuple feeds
   both the pump's dispatch and `list_commands`.
3. Add a `@vtool` wrapper in `mcp-server/<area>_tools.py` and import that module
   from `mcp-server/fork_tools.py` (one line; `vwx_mcp_server.py` stays untouched).
4. Add `"your_verb": "<tag>"` to `mcp-server/tool_tags.py`, and the module name to
   `tests/test_tool_tags.py`'s scan list.
5. Smoke-test against a live VW (no CI can — every tool hits the running app).

## Environment variables

Set in `bridge/vwx-mcp.bat`.

| Var | Default | Purpose |
|---|---|---|
| `VWX_TOOLSET` | `full` | Toolset preset: `full`/`gis`/`modeling`/`baumkataster`/`minimal` |
| `VWX_CALL_TIMEOUT` | `60` | Per-tool timeout (s) — native `@mcp.tool(timeout=)` on every tool |
| `VWX_TASKS` | _(off)_ | Opt long-running tools into the MCP Tasks extension. Needs `pip install 'fastmcp[tasks]'` **and** a Tasks-capable client; warns + stays off otherwise |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(off)_ | If set, exports fastmcp's spans via OTLP. Needs `opentelemetry-exporter-otlp` |
| `MCP_TRANSPORT` | `stdio` | `streamable-http` for the HTTP server, `stdio` for local |
| `FASTMCP_HOST` / `FASTMCP_PORT` | `127.0.0.1` / `8082` | HTTP bind (a non-local bind logs a warning — set a token) |
| `VWX_MCP_TOKEN` | _(off)_ | Shared secret; clients must send `Authorization: Bearer <token>` |
| `VWX_ORIGIN_GUARD` | `1` | Strict Host/Origin check against browser pages / DNS rebinding |
| `VWX_DENY_ROOTS` | `Y:\;\\` | `;`-separated roots that exports, saves and `open_document` refuse |
| `VWX_DRAIN_BUDGET_S` | `2.0` | (VW process env) max seconds per drain before the UI gets a turn |
| `DESKTOP_HOST` / `VWX_MCP_PORT` | `127.0.0.1` / `9878` | VW bridge socket |

## Reliability & observability notes

- **Concurrency**: the bridge has a single socket shared by all tools; `send_command`
  serializes one round-trip at a time under a lock. Concurrent tool calls are safe
  but execute sequentially against VW (VW's `vs.*` runs on one main thread anyway).
- **Logs**: each call logs `tool=<name> cid=<id> ms=<latency> status=ok|err`. The
  `cid` also travels in the command envelope (`_cid`) so VW-side logs can be matched.
