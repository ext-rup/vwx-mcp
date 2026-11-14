"""Every fork tool module, imported in one place.

vwx_mcp_server.py (vendored) imports THIS module in a single line, so adding a
new fork tool module never grows the diff against upstream. Each module grabs
the running FastMCP instance itself (see spotlight_tools.py) and registers its
tools with `vtool`.
"""
import spotlight_tools   # noqa: F401  M1/M2/M5 - Lighting Devices, patch, paperwork
import connectcad_tools  # noqa: F401  M6 - ConnectCAD devices, circuits, cables
import braceworks_tools  # noqa: F401  M6 - Braceworks hoists, trusses, loads
import mvr_tools         # noqa: F401  M6 - MVR export/import (GUI) + inspect
