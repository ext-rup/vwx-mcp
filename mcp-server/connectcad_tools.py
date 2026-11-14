"""ConnectCAD MCP tools — the fork layer (M6).

Kept out of vwx_mcp_server.py for the same reason as spotlight_tools.py: that
file stays vendored and rebaseable. The verbs live in
vwx-plugin/commands_connectcad.py; this module only declares the MCP surface.

Registered by `import connectcad_tools` from fork_tools.py, which
vwx_mcp_server.py imports in one line.
"""
import sys

from fastmcp import Context

_server = sys.modules.get('__main__')
if _server is None or not hasattr(_server, 'vtool'):
    import vwx_mcp_server as _server
cmd, vtool = _server.cmd, _server.vtool


# ═══════════════════════════════════════════════════════════════════
# ConnectCAD — reads (record-driven, no CC_GetCircuitSource: it crashes VW)
# ═══════════════════════════════════════════════════════════════════

@vtool
def get_connectcad_devices(ctx: Context, room: str = None, rack: str = None,
                           type: str = None, criteria: str = None,
                           sort_by: str = "tag", limit: int = 500,
                           raw: bool = False) -> str:
    """ConnectCAD devices with location, power, weight and BTU.

    `room`/`rack`/`type` filter by exact value (case-insensitive); `criteria`
    adds a raw Vectorworks criteria fragment. `raw: true` returns every record
    field per device, so a mapping miss is never a dead end."""
    p = {"sort_by": sort_by, "limit": limit, "raw": raw}
    for k, v in (("room", room), ("rack", rack), ("type", type),
                 ("criteria", criteria)):
        if v: p[k] = v
    return cmd("get_connectcad_devices", p)


@vtool
def get_connectcad_circuits(ctx: Context, signal: str = None,
                            device: str = None, criteria: str = None,
                            sort_by: str = "number", limit: int = 500,
                            raw: bool = False) -> str:
    """Circuits with full source -> destination topology.

    Each circuit carries source/dest device, tag, socket, connector, room,
    rack, rack U and slot, plus the calculated cable length. `device` matches
    either end. Topology comes from the record: CC_GetCircuitSource/Dest
    hard-crash Vectorworks 2027 and are never called."""
    p = {"sort_by": sort_by, "limit": limit, "raw": raw}
    for k, v in (("signal", signal), ("device", device), ("criteria", criteria)):
        if v: p[k] = v
    return cmd("get_connectcad_circuits", p)


@vtool
def get_connectcad_cables(ctx: Context, criteria: str = None,
                          sort_by: str = "id", limit: int = 500) -> str:
    """Cable paths: id, cable count, length, circuits, location, total length."""
    p = {"sort_by": sort_by, "limit": limit}
    if criteria: p["criteria"] = criteria
    return cmd("get_connectcad_cables", p)


@vtool
def get_connectcad_rooms(ctx: Context, sort_by: str = "room",
                         limit: int = 500) -> str:
    """Rooms with what is in them: device, rack and drop-point counts."""
    return cmd("get_connectcad_rooms", {"sort_by": sort_by, "limit": limit})


@vtool
def get_connectcad_racks(ctx: Context, sort_by: str = "rack",
                         limit: int = 500) -> str:
    """Racks with their equipment items (name, make/model, U, slot)."""
    return cmd("get_connectcad_racks", {"sort_by": sort_by, "limit": limit})


@vtool
def get_connectcad_signals(ctx: Context, names: list = None) -> str:
    """The signal catalog (CC_GetSignalData) for the document's signals.

    Columns are 1-based and the label map is inferred, so every entry keeps
    `raw_columns` and the result reports `labels_verified`."""
    p = {}
    if names: p["names"] = names
    return cmd("get_connectcad_signals", p)


@vtool
def get_connectcad_connectors(ctx: Context, names: list = None) -> str:
    """The connector catalog (CC_GetConnectorData) for the document's connectors."""
    p = {}
    if names: p["names"] = names
    return cmd("get_connectcad_connectors", p)


# ═══════════════════════════════════════════════════════════════════
# ConnectCAD — paperwork
# ═══════════════════════════════════════════════════════════════════

@vtool
def get_connectcad_schedule(ctx: Context, kind: str = "equipment",
                            criteria: str = None, sort_by: str = None,
                            limit: int = 500) -> str:
    """A ConnectCAD schedule as JSON rows.

    kind: equipment | circuit | cable | rack | room. Same data the worksheet
    verb writes, so you can diff the two."""
    p = {"kind": kind, "limit": limit}
    for k, v in (("criteria", criteria), ("sort_by", sort_by)):
        if v: p[k] = v
    return cmd("get_connectcad_schedule", p)


@vtool
def connectcad_worksheet(ctx: Context, kind: str = "equipment",
                         name: str = None, criteria: str = None,
                         sort_by: str = None, limit: int = 500,
                         place: bool = False, x: float = 0, y: float = 0,
                         verify: bool = True) -> str:
    """Build a real Vectorworks database worksheet for a ConnectCAD schedule.

    The column formulas are generated from the record fields the objects
    report, then every subrow is read back and compared with the schedule:
    `verified: false` names the column that differs instead of returning a
    sheet that silently shows nothing."""
    p = {"kind": kind, "limit": limit, "place": place, "x": x, "y": y,
         "verify": verify}
    for k, v in (("name", name), ("criteria", criteria), ("sort_by", sort_by)):
        if v: p[k] = v
    return cmd("connectcad_worksheet", p)
