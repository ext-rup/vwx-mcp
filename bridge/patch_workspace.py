"""Add the VWX bridge entries to a Vectorworks workspace (.vww) by editing XML.

Vectorworks 2018+ stores workspaces as XML. The Workspace Editor is a GUI-only
tool, which makes the "add the menu command" setup step impossible to automate
on a machine without a working menu bar. This script does the same edit
directly:

  * copies the shipped workspace into the user folder (a user copy wins over
    the one in Program Files, and Program Files needs admin to write),
  * appends the bridge menu items to the Tools menu,
  * defines the items (with the Ctrl+Shift+B accelerator on "VWX Bridge Start"),
  * points the preference `defaultWorkspace` at the patched user copy — without
    this Vectorworks keeps loading the Program Files file and the added menu
    entries never appear (verified on VW2027).

Run it with Vectorworks CLOSED, then start Vectorworks: the workspace is read
at startup. Idempotent — running it twice does not duplicate the entries.

    python bridge/patch_workspace.py --workspace Spotlight --year 2027
    python bridge/patch_workspace.py --workspace Spotlight --year 2027 --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

# Menu items to add, in menu order.
#   element suffix / UniversalName, ResourceManagerID, shortcut (key, modifiers)
# Modifiers in VW's workspace format: 1 = Ctrl, 2 = Shift, 3 = Ctrl+Shift,
# 4 = Alt (see "Save"=1, "Save As..."=3 in the shipped Spotlight workspace).
#
# ResourceManagerID: 0 works for BUILT-IN commands, but a plug-in menu command
# is dropped silently unless it carries the ID Vectorworks assigned it. VW
# numbers plug-in commands sequentially after the last built-in one (the
# Workspace Editor gave "VWX Bridge Start" 401, right after WorkspacesDialog's
# 400), so the patch allocates max(existing)+1 — see _next_rm_id().
ITEMS = [
    # The Python menu command that actually drains the job queue (the only
    # context where document mutation is safe).
    ("VWX_x20Bridge_x20Start", "auto", ("B", 3)),
]

# Native palette commands (BraceWorxsVwxPlg.vlb). Only added with --native:
# they are dropped again on the next save when that plug-in is not loaded.
NATIVE_ITEMS = [
    ("ExtMenuShowVwxBridge", "auto", None),
    ("ExtMenuVwxPump", "auto", None),
]

TOOLS_MENU_DISPLAY = "Tools"


def _user_workspaces(year: str) -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("APPDATA is not set — this script is Windows-only")
    return Path(appdata) / "Nemetschek" / "Vectorworks" / year / "Workspaces"


def _shipped_workspaces(year: str) -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / f"Vectorworks {year}" / "Workspaces"


def _prefs_file(year: str) -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("APPDATA is not set — this script is Windows-only")
    return (Path(appdata) / "Nemetschek" / "Vectorworks" / year
            / "Settings" / "Vectorworks Preferences.xml")


def set_default_workspace(prefs: Path, target: Path) -> str:
    """Point <defaultWorkspace> at `target`. Returns a status note."""
    if not prefs.exists():
        return f"prefs not found ({prefs}) — set the workspace in Vectorworks"
    raw = prefs.read_bytes()
    text = raw.decode("utf-8-sig")
    m = re.search(r"<defaultWorkspace>(.*?)</defaultWorkspace>", text, re.S)
    if not m:
        return "no <defaultWorkspace> entry — set the workspace in Vectorworks"
    current = m.group(1).strip()
    if current.lower() == str(target).lower():
        return f"defaultWorkspace already {target.name} (user copy)"
    text = text[:m.start(1)] + str(target) + text[m.end(1):]
    prefs.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    return f"defaultWorkspace {current} -> {target}"


def _next_rm_id(text: str) -> int:
    """First free plug-in ResourceManagerID.

    Built-in commands use small numbers, plug-in commands sit in 400..999, and
    menu chunks use 2000+. Vectorworks itself picked 401 for a new plug-in
    command in a workspace whose plug-in block ended at 435, i.e. it takes the
    first free slot rather than max+1 — mirror that so a scripted patch and a
    Workspace-Editor patch produce the same file.
    """
    ids = [int(m) for m in re.findall(r"<ResourceManagerID>(-?\d+)</ResourceManagerID>", text)]
    used = {i for i in ids if 0 < i < 1000}
    for candidate in range(401, 1000):
        if candidate not in used:
            return candidate
    return max(used | {400}) + 1


def _item_xml(name: str, rm_id: int, shortcut, nl: str = "\r\n") -> str:
    lines = [
        f"    <net.vectorworks.workspaceitem.menuitem.{name}>",
        f"      <ResourceManagerID>{rm_id}</ResourceManagerID>",
        f"      <UniversalName>{name}</UniversalName>",
    ]
    if shortcut:
        key, mods = shortcut
        lines.append(f'      <Shortcut Key="{key}" Modifiers="{mods}"/>')
    lines.append(f"    </net.vectorworks.workspaceitem.menuitem.{name}>")
    return nl.join(lines)


def patch(text: str, items=ITEMS) -> tuple[str, list[str]]:
    """Return (new_text, notes). Raises ValueError if the file is unexpected.

    A workspace has TWO relevant sections:

      <Menus>      the menu structure — which menu contains which item
      <MenuItems>  the item definitions — ResourceManagerID, UniversalName,
                   Shortcut

    A reference without a definition in <MenuItems> is silently dropped by
    Vectorworks (verified: entries appended to <Menus> never showed up), and a
    plug-in command with ResourceManagerID 0 is dropped as well, so both edits
    and a real ID are required.
    """
    notes: list[str] = []
    nl = "\r\n" if "\r\n" in text else "\n"

    # 0. Section bounds first: a definition is only valid inside the top-level
    #    <MenuItems> section, so the repair step below must know where that is.
    menus_end = text.find("</Menus>")
    top = text.find(nl + "  <MenuItems>")
    if top < 0:
        raise ValueError("no top-level <MenuItems> section")
    end_items = text.find(nl + "  </MenuItems>", top)
    if end_items < 0:
        raise ValueError("no closing </MenuItems> for the top-level section")
    if menus_end < 0 or menus_end > top:
        raise ValueError("unexpected section order (no <Menus> before <MenuItems>)")

    # 0b. Remove definitions this script may have written in the wrong place
    #     (older versions appended them to <Menus>), so a re-run repairs them.
    for name, _rm, _sc in items:
        block = re.compile(
            r"[ \t]*<net\.vectorworks\.workspaceitem\.menuitem\." + re.escape(name)
            + r">.*?</net\.vectorworks\.workspaceitem\.menuitem\." + re.escape(name)
            + r">[ \t]*\r?\n",
            re.S,
        )
        head, tail = text[:menus_end], text[menus_end:]
        head, n = block.subn("", head)
        if n:
            notes.append(f"{name}: removed misplaced definition")
            text = head + tail

    # 1. Locate the Tools menu block and its <MenuItems> list.
    marker = f"<DisplayName>{TOOLS_MENU_DISPLAY}</DisplayName>"
    at = text.find(marker)
    if at < 0:
        raise ValueError(f"no menu named {TOOLS_MENU_DISPLAY!r} in this workspace")
    open_tag = text.rfind("<net.vectorworks.workspaceitem.menu.", 0, at)
    close_items = text.find("</MenuItems>", at)
    if open_tag < 0 or close_items < 0:
        raise ValueError("could not delimit the Tools menu")

    # 2. Insert references, skipping ones already present. Insert at the start
    # of the closing tag's line so the existing indentation is not doubled.
    refs = []
    for name, _rm, _sc in items:
        ref = f"<net.vectorworks.workspaceitem.menuitem.{name}/>"
        if ref in text[open_tag:close_items]:
            notes.append(f"{name}: already in the menu")
            continue
        refs.append(f"        {ref}")
    if refs:
        at = _line_start(text, close_items)
        text = text[:at] + nl.join(refs) + nl + text[at:]

    # 3. Insert the item definitions into the top-level <MenuItems> section
    #    (indented by exactly two spaces; the nested ones are deeper).
    #    Re-read the bounds: step 2 may have shifted them.
    top = text.find(nl + "  <MenuItems>")
    end_items = text.find(nl + "  </MenuItems>", top)
    next_id = _next_rm_id(text)
    defs = []
    for name, rm_id, sc in items:
        if f"<net.vectorworks.workspaceitem.menuitem.{name}>" in text[top:end_items]:
            notes.append(f"{name}: already defined")
            continue
        if rm_id == "auto":
            rm_id = next_id
            next_id += 1
        defs.append(_item_xml(name, rm_id, sc, nl))
    if defs:
        at = _line_start(text, end_items)
        text = text[:at] + nl.join(defs) + nl + text[at:]

    return text, notes


def _line_start(text: str, pos: int) -> int:
    """Index of the first character of the line containing `pos`."""
    nl = text.rfind("\n", 0, pos)
    return 0 if nl < 0 else nl + 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default="Spotlight", help="workspace name without .vww")
    ap.add_argument("--year", default="2027", help="Vectorworks version, e.g. 2027")
    ap.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    ap.add_argument("--no-set-default", action="store_true",
                    help="leave the defaultWorkspace preference alone")
    ap.add_argument("--native", action="store_true",
                    help="also add the native palette commands (needs BraceWorxsVwxPlg)")
    args = ap.parse_args(argv)

    items = list(ITEMS) + (list(NATIVE_ITEMS) if args.native else [])

    shipped = _shipped_workspaces(args.year) / f"{args.workspace}.vww"
    user_dir = _user_workspaces(args.year)
    target = user_dir / f"{args.workspace}.vww"

    source = target if target.exists() else shipped
    if not source.exists():
        print(f"error: neither {target} nor {shipped} exists", file=sys.stderr)
        return 2

    raw = source.read_bytes()
    text = raw.decode("utf-8-sig")
    new_text, notes = patch(text, items)
    for note in notes:
        print(f"  {note}")

    if new_text == text:
        print("workspace already patched")
        if not args.no_set_default and not args.dry_run:
            print("  " + set_default_workspace(_prefs_file(args.year), target))
        return 0

    if args.dry_run:
        import difflib

        diff = difflib.unified_diff(
            text.splitlines(), new_text.splitlines(), "before", "after", lineterm="", n=2
        )
        print("\n".join(list(diff)[:60]))
        return 0

    user_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(".vww.bak"))
    elif not args.dry_run:
        shutil.copy2(shipped, target.with_suffix(".vww.bak"))
    target.write_bytes(b"\xef\xbb\xbf" + new_text.encode("utf-8"))
    print(f"patched {target}")

    if not args.no_set_default:
        print("  " + set_default_workspace(_prefs_file(args.year), target))

    print("start Vectorworks; the entries are in the Tools menu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
