"""vwx_verbs.py — the fork's verb modules, in dispatch order.

commands.py (vendored upstream) and vwx_pump.py both need this list: one to
merge the verbs into `list_commands`, the other to find them in `_dispatch`.
Keeping it here means a new module is registered in ONE place and the two
cannot drift apart.

A module listed here must expose plain `def verb(params)` functions and must be
importable from the plug-in directory. A module that fails to import is
skipped (the pump logs it) — a broken fork module must never take the vendored
verbs down with it.
"""

MODULES = (
    'commands_spotlight',     # M1/M2/M5: Lighting Devices, patch, paperwork
    'commands_connectcad',    # M6: ConnectCAD devices, circuits, cables, rooms
    'commands_braceworks',    # M6: Braceworks hoists, trusses, load summary
)
