"""Spotlight (entertainment lighting) MCP tools — the fork layer.

Kept OUT of vwx_mcp_server.py so that file stays a vendored, rebaseable upstream
file (QUICKSTART rule 4). The verbs themselves live in
vwx-plugin/commands_spotlight.py; this module only declares the MCP surface.

Registered by a single `import spotlight_tools` at the end of vwx_mcp_server.py:
`vtool` and `cmd` are already defined by then, so the circular import is safe.
"""
import sys

from fastmcp import Context

# The server is normally started as a script, so its module is `__main__`; a
# plain `import vwx_mcp_server` would build a SECOND FastMCP instance and
# register these tools on the wrong one (they then answer "Unknown tool").
_server = sys.modules.get('__main__')
if _server is None or not hasattr(_server, 'vtool'):
    import vwx_mcp_server as _server
cmd, vtool = _server.cmd, _server.vtool


@vtool
def find_objects(ctx: Context, criteria: str = "ALL", limit: int = 500) -> str:
    """Find objects with a raw Vectorworks criteria string; returns UUIDs + count.

    This is the general query entry point — anything the worksheet criteria
    engine accepts works, e.g. "(PON='Lighting Device')",
    "((R in ['Part Info']))", "C='Rigging'", "SEL=TRUE", "L='Lighting'".
    Objects of type 86 also report their plug-in name ('plugin').
    """
    return cmd("find_objects", {"criteria": criteria, "limit": limit})


# ═══════════════════════════════════════════════════════════════════
# Spotlight (entertainment lighting)
# ═══════════════════════════════════════════════════════════════════

@vtool
def get_spotlight_devices(ctx: Context, criteria: str = None, position: str = None,
                          limit: int = 500, raw: bool = False) -> str:
    """List Lighting Devices with patch/focus fields (channel, dimmer, universe,
    address, position, unit number, device type, symbol, purpose, colour, gobo,
    focus) plus plan coordinates. raw=true adds every record field per device.

    Fields are resolved through spotlight_params.json; anything that could not
    be resolved is listed in 'unresolved' rather than silently omitted.
    """
    p = {"limit": limit, "raw": raw}
    if criteria: p["criteria"] = criteria
    if position: p["position"] = position
    return cmd("get_spotlight_devices", p)


@vtool
def get_spotlight_device(ctx: Context, object_id: str) -> str:
    """Everything one Lighting Device exposes: mapped fields, all raw record
    fields, cell count and the accessory list with 2D/3D placement."""
    return cmd("get_spotlight_device", {"object_id": object_id})


@vtool
def get_spotlight_positions(ctx: Context, criteria: str = None, limit: int = 500) -> str:
    """Lighting Devices grouped by hanging position, with counts and UUIDs."""
    p = {"limit": limit}
    if criteria: p["criteria"] = criteria
    return cmd("get_spotlight_positions", p)


@vtool
def get_spotlight_patch(ctx: Context, criteria: str = None, limit: int = 500) -> str:
    """Patch sheet: one row per Lighting Device (channel, dimmer, universe,
    address, footprint, position, unit number, type, purpose) plus the conflicts
    a patch sheet exists to catch — duplicate channel, duplicate universe/address,
    overlapping DMX footprints, and devices with no channel or address."""
    p = {"limit": limit}
    if criteria: p["criteria"] = criteria
    return cmd("get_spotlight_patch", p)


@vtool
def get_spotlight_focus(ctx: Context, criteria: str = None, limit: int = 500) -> str:
    """Focus chart: devices grouped by focus, with position, channel, colour,
    gobo, pan/tilt and purpose per device."""
    p = {"limit": limit}
    if criteria: p["criteria"] = criteria
    return cmd("get_spotlight_focus", p)


@vtool
def get_spotlight_accessories(ctx: Context, object_id: str = None,
                              criteria: str = None, limit: int = 500) -> str:
    """Accessory inventory: per device, per cell accessory counts and each
    accessory's 2D/3D placement. Pass object_id for one device, or criteria for
    all of them."""
    p = {"limit": limit}
    if object_id: p["object_id"] = object_id
    if criteria: p["criteria"] = criteria
    return cmd("get_spotlight_accessories", p)


@vtool
def get_spotlight_params(ctx: Context, live: bool = False, limit: int = 50) -> str:
    """The Lighting Device parameter catalog: universal (worksheet) names, types
    and a sample value each — the names LDevice_GetParam* addresses.

    Reads vwx-plugin/spotlight_params.json; live=true re-enumerates from the
    devices in the open document instead (no file written).
    """
    return cmd("get_spotlight_params", {"live": live, "limit": limit})


@vtool
def dump_spotlight_params(ctx: Context, limit: int = 50, path: str = None) -> str:
    """Enumerate the Lighting Device parameter catalog from the live document and
    write vwx-plugin/spotlight_params.json.

    Run this once per Vectorworks year/locale: it is the only way to learn the
    universal names the other Spotlight verbs resolve against. Needs a document
    that actually contains a Lighting Device.
    """
    p = {"limit": limit}
    if path: p["path"] = path
    return cmd("dump_spotlight_params", p)


@vtool
def get_spotlight_report(ctx: Context, kind: str = "channel_hookup",
                         criteria: str = None, limit: int = 500,
                         sort_by: str = None) -> str:
    """The data behind a paperwork sheet, as JSON (no worksheet needed).

    kind: channel_hookup | instrument_schedule | patch_sheet | focus_chart |
    weight_report. weight_report adds weight_kg/power_w per device and
    by_position totals. Same rows the worksheet gets, so a report can be
    printed, diffed or archived without touching the document."""
    p = {"kind": kind, "limit": limit}
    if criteria: p["criteria"] = criteria
    if sort_by: p["sort_by"] = sort_by
    return cmd("get_spotlight_report", p)


@vtool
async def spotlight_worksheet(ctx: Context, kind: str = "channel_hookup",
                              name: str = None, criteria: str = None,
                              sort_by: str = None, place: bool = False,
                              x: float = 0, y: float = 0,
                              verify: bool = True, limit: int = 500) -> str:
    """Build a real Vectorworks worksheet for a paperwork deliverable.

    kind: channel_hookup | instrument_schedule | patch_sheet | focus_chart |
    weight_report. Column formulas come from the universal names the live record
    reports, so a localized Vectorworks still fills them. verify (default true)
    reads every cell back and compares it with the plot: verified:false means
    the sheet on screen does not match the data."""
    p = {"kind": kind, "place": place, "x": x, "y": y, "verify": verify,
         "limit": limit}
    if name: p["name"] = name
    if criteria: p["criteria"] = criteria
    if sort_by: p["sort_by"] = sort_by
    return cmd("spotlight_worksheet", p)


@vtool
async def set_spotlight_patch(ctx: Context, fields: dict = None,
                              assignments: list = None, object_ids: list = None,
                              criteria: str = None, dry_run: bool = False,
                              limit: int = 500) -> str:
    """Write patch/focus fields on Lighting Devices, with a before-value journal.

    fields: {"channel": "101", "universe_address": "1/101", "position": "FOH"}
    applied to every selected device; assignments: [{"object_id": ..., "fields":
    {...}}] for per-device values. dry_run reports what would change. Every write
    is read back, so a SetRField that does not take comes back as ok:false.
    Returns batch_id for revert_last."""
    p = {"limit": limit, "dry_run": dry_run}
    if fields: p["fields"] = fields
    if assignments: p["assignments"] = assignments
    if object_ids: p["object_ids"] = object_ids
    if criteria: p["criteria"] = criteria
    return cmd("set_spotlight_patch", p)


@vtool
async def renumber_spotlight(ctx: Context, order: str = "x",
                             start_channel: int = 1, channel_step: int = 1,
                             start_universe: int = 1, start_address: int = 1,
                             universe_size: int = 512, criteria: str = None,
                             object_ids: list = None, dry_run: bool = False,
                             limit: int = 500) -> str:
    """Sequential channel + DMX renumber across a selection (one undo step).

    Devices are ordered left-to-right (order="x") by default; "y", "name",
    "channel" and "address" also work. Addresses step by each fixture's DMX
    footprint and roll into the next universe when they would not fit."""
    p = {"order": order, "start_channel": start_channel,
         "channel_step": channel_step, "start_universe": start_universe,
         "start_address": start_address, "universe_size": universe_size,
         "dry_run": dry_run, "limit": limit}
    if criteria: p["criteria"] = criteria
    if object_ids: p["object_ids"] = object_ids
    return cmd("renumber_spotlight", p)


@vtool
async def revert_last(ctx: Context, batch_id: str = None,
                      dry_run: bool = False) -> str:
    """Undo the most recent Spotlight write batch from the journal.

    Defaults to the newest batch that was not reverted yet. Refuses when the
    batch belongs to another document, and skips fields that already hold their
    old value (someone undid it by hand)."""
    p = {"dry_run": dry_run}
    if batch_id: p["batch_id"] = batch_id
    return cmd("revert_last", p)
