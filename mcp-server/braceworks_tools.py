"""Braceworks MCP tools — the fork layer (M6).

Verbs live in vwx-plugin/commands_braceworks.py; this module only declares the
MCP surface. Registered by `import braceworks_tools` from fork_tools.py.
"""
import sys

from fastmcp import Context

_server = sys.modules.get('__main__')
if _server is None or not hasattr(_server, 'vtool'):
    import vwx_mcp_server as _server
cmd, vtool = _server.cmd, _server.vtool


@vtool
def get_braceworks_hoists(ctx: Context, origin: str = None,
                          function: str = None, overloaded_only: bool = False,
                          sort_by: str = "number", limit: int = 500,
                          raw: bool = False) -> str:
    """Braceworks hoists with rated capacity, point load and reaction force.

    Each hoist carries `load_ratio` and `overloaded`; a hoist with no rated
    maximum reports `capacity_known: false` instead of pretending to be fine.
    `overloaded_only` returns just the ones over their limit."""
    p = {"sort_by": sort_by, "limit": limit, "raw": raw,
         "overloaded_only": overloaded_only}
    for k, v in (("origin", origin), ("function", function)):
        if v: p[k] = v
    return cmd("get_braceworks_hoists", p)


@vtool
def get_braceworks_trusses(ctx: Context, sort_by: str = "name",
                           limit: int = 500) -> str:
    """Straight and curved trusses: length, profile, distributed weight."""
    return cmd("get_braceworks_trusses", {"sort_by": sort_by, "limit": limit})


@vtool
def get_braceworks_loads(ctx: Context) -> str:
    """Load summary per hoist origin: hoist count, total load, total capacity.

    The number a rigger asks for first — hoists without an origin are grouped
    separately and reported as `unassigned`."""
    return cmd("get_braceworks_loads", {})
