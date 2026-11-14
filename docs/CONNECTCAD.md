# ConnectCAD + Braceworks (M6)

Twelve verbs across two modules, all read-only, all verified against a live
Vectorworks 2027 on 2026-11-14.

| Module | Verbs | Tag |
|---|---|---|
| `vwx-plugin/commands_connectcad.py` | `get_connectcad_devices`, `_circuits`, `_cables`, `_rooms`, `_racks`, `_signals`, `_connectors`, `_schedule`, `connectcad_worksheet` | `connectcad` |
| `vwx-plugin/commands_braceworks.py` | `get_braceworks_hoists`, `_trusses`, `_loads` | `braceworks` |

Test documents: `Libraries/ConnectCAD/Samples/Sample Worksheets.vwx` (19
devices, 3 circuits, 4 cable paths, 3 racks, 2 rooms) for ConnectCAD; a
document with one `HoistVW`, one `Straight Truss` and one `Curved Truss` for
Braceworks.

## The layer is record-driven, like Spotlight

Every ConnectCAD and Braceworks object is a type-86 plug-in object whose
parameters live in a parametric record. The record name **is** the plug-in name,
and the field names are stable:

| Record | Fields | What is in it |
|---|---|---|
| `Device` | 35 | `tag`, `name`, `type`, `make`, `model`, `loc_room`, `loc_rack`, `loc_rackU`, `loc_slot`, `power`, `weight`, `heightU`, `width_R`, `modular`, `nslots`, `HasEquipment`, `BTU` |
| `Circuit` | 62 | `Number`, `Signal`, `Cable`, `Circuits`, `Src_Dev_Name/Tag`, `Src_Skt_Name`, `Src_Signal`, `Src_Skt_Conn`, `Src_Room/Rack/RackU/Slot`, the same `Dst_*` set, `CableCalculatedLength` |
| `CablePathObject` | 13 | `ID`, `Location`, `CableCount`, `Length`, `Cable Area`, `__Circuits Count` |
| `Room2D` | 7 | `RoomID`, `ExtrudeHeight`, `Is2DOnly` |
| `Rack19in3D` | 35 | `RackID`, `Height/Width/Depth`, `Weight`, `RoomID`, `RackType`, `Power` |
| `RackFrame` | 40 | `name`, `make`, `model`, `loc_room`, `loc_rack`, `heightRU` |
| `EquipItem` | 49 | `name`, `make`, `model`, `rack ID`, `rack U`, `slot ID`, `heightU` |
| `CC Drop Point` | 10 | `Category`, `Name`, `Symbol`, `RoomID`, `CableSlack` |
| `HoistVW` | 101 | see below |
| `Straight Truss` | 30 | `LineLength`, `Profile`, `Connection`, `Height`, `Width`, `DistrWeightStr`, `DistributedWeight`, `Hanging Angle` |
| `Curved Truss` | 29 | `Diameter`, `Total Arc`, `Segment Arc`, `Radius`, + the same profile/weight fields |

## Findings that are now coded in

**`CC_GetCircuitSource` / `CC_GetCircuitDest` hard-crash Vectorworks 2027.**
Not an exception — the process dies mid-script with no dialog, so the pump never
returns and every later job times out. Reproduced twice. They are not called
anywhere; the `Src_*` / `Dst_*` record fields carry the same topology (device,
tag, socket, signal, connector, room, rack, rack U, slot).

**Numbers are localized text, exponent included.** `'-1,2e01'`,
`'4,826e02'`, `'7,252844172117577e03'`. `float()` fails on the comma *and* the
exponent, so `_cnum()` normalizes first (when both separators appear the last
one is decimal; otherwise `,` is decimal). `'0 sq m'` → `0.0`, `''` → `None`.

**Braceworks keeps two parallel values per mass**, a localized string and a raw
number in the document's internal unit. On a metric document that unit is
**grams**: a 1/2-ton hoist reports `MaximumLoad = 50000` next to
`MaximumLoadStr = '50,00 kg'`. Reporting the raw number as kilograms would
understate every load by 1000×, so the scale is *derived from the pair the
object itself reports* (`mass_scale: 1000.0`) and both forms are returned.

**The hoist plug-in is `HoistVW`, not `Hoist`.** `vs.CreateCustomObject('Hoist',
…)` builds a different, legacy object ("Hoist (Legacy)") with a small record and
none of the load fields — a schedule built on it would be full of blanks that
look like an empty rig.

**The signal/connector catalogs are 1-based.** `CC_GetSignalData(name, col)` and
`CC_GetConnectorData(name, col)` take a *name* and a column index; column 0 and
the first empty column return `''`. Live sample (signal `HDMI`):

```
col 1 'M'                                col 1 'HDMI connector'
col 2 'HDMI'                             col 2 'con_HDMI'
col 3 'High-Definition Multimedia ...'    col 3 'HDMI'
col 4 'HDMI'                             col 4 'HDMI'
col 6 'Video'
```

The label map is **inferred**, so every entry keeps `raw_columns` and the result
says how far the inference could be checked: `labels_verified: true` when a
column echoes the queried name (signals), `null` when none does (connectors).

**Creating a hoist is not headless.** `CreateCustomObject('HoistVW', …)` opens
"Object Properties: HoistVW", and the first one in a document also triggers a
symbol import with a "Resource Name Conflict" dialog. The reads need none of
that; a scripted rig build is a dialog dance.

## Reads

```jsonc
get_connectcad_circuits {"signal": "HDMI"}
  → count 3, strategy "criteria", units {"unit": "mm", ...}
    circuits[0]: {"number": "1111", "signal": "HDMI",
                  "source_device": "Switcher 1", "source_socket": "HDMI_OUT 1",
                  "source_rack": "R1", "source_rack_u": "21",
                  "dest_device": "Transmitter", "dest_rack": "C1",
                  "dest_rack_u": "5", "dest_slot": "4",
                  "length": "4.5", "length_num": 4.5}
```

`get_connectcad_rooms` and `_racks` add what is *in* each one (device/rack/drop
counts, rack contents with U and slot). `_cables` adds `total_length`.

`get_braceworks_hoists` is where the capacity check lives:

```jsonc
{"number": "1", "type": "1/2 Ton", "max_load_kg": 50.0, "load_kg": 60.0,
 "mass_scale": 1000.0, "load_ratio": 1.2, "overloaded": true,
 "origin": "Origin A", "reaction_force_kg": 1.0}
```

A hoist with no rated maximum reports `capacity_known: false` and
`overloaded: null` — *not* `false`. `overloaded_only: true` returns just the
ones over their limit. `get_braceworks_loads` totals per origin (hoists, load,
capacity, reaction force, overloaded count) and reports hoists with no origin as
`unassigned`.

## Paperwork

`get_connectcad_schedule` returns rows for `equipment`, `circuit`, `cable`,
`rack` or `room`. `connectcad_worksheet` builds a real database worksheet from
the same rows and **verifies it cell by cell** against them — the same contract
as `spotlight_worksheet`:

```
connectcad_worksheet {kind: "circuit", name: "CC Circuit Live"}
  → subrows 3, verified: true
```

Verified live: circuit (3 subrows), equipment (19), rack (3), room (2),
cable (4) — all `verified: true`.

Two things the read-back had to learn:

- **The database binding lives in column 0.** `SetWSCellFormula(ws, row, 1, …,
  '=DATABASE(…)')` stores the text in a data column and recalculates to **zero
  subrows** — indistinguishable from an empty sheet. Column 0 is the binding
  cell; data columns are 1-based.
- **A popup field renders its choice label, not the stored value.** A device
  stores `type = 'VideoJack'`; the cell shows `Video Jackfield`. Comparing text
  would report a correct sheet as wrong, so columns whose record field is
  `GetFldType == 8` are checked for presence and flagged `rendered: true`.

## Not done

- **MVR / GDTF.** The `vs` index has **zero** GDTF or MVR functions on VW2027;
  import/export is menu-command only (`DoMenuTextByName`), and like the other
  export verbs it puts up a dialog. Not wrapped — a tool that opens a modal
  dialog cannot be automated and pretending otherwise is worse than saying so.
- **ConnectCAD writes.** Devices/circuits are placed and routed by the
  ConnectCAD UI; the record can be edited with `SetRField`, but a device moved
  by its record alone does not reconnect the circuit, so a write verb would
  produce a plot that looks right and is wrong.
- **Braceworks worksheets.** `connectcad_worksheet` covers the ConnectCAD
  schedules; a hoist schedule sheet would reuse the same machinery and is the
  obvious next step.
