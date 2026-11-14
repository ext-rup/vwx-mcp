"""MVR (My Virtual Rig) tools — export, import, inspect.

MVR has **no `vs.*` surface** on Vectorworks 2027: the SDK index has zero GDTF
or MVR functions, and `DoMenuTextByName('Export MVR', 0)` raises a VW script
error because the command is not scriptable. So these tools drive the menu and
its dialogs with real input (see `vwx_gui.py`), and `inspect_mvr` reads the
resulting file in plain Python — no Vectorworks, no GUI.

That split is deliberate: the part that cannot be automated (choosing a folder
in VW's file dialog) is reported, and the part that can (what ended up in the
file) is answered exactly.
"""
import asyncio
import sys

from fastmcp import Context

_server = sys.modules.get('__main__')
if _server is None or not hasattr(_server, 'vtool'):
    import vwx_mcp_server as _server
cmd, vtool = _server.cmd, _server.vtool


def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


@vtool
async def export_mvr(ctx: Context, path: str, inspect: bool = True) -> str:
    """Export the front document to an MVR file (drives the VW menu + dialogs).

    MVR is not scriptable in Vectorworks, so this clicks through File ▸ Export ▸
    Export MVR... with real input, answers the options dialog with its defaults
    (all objects in drawing, all object types), types the file name and presses
    Save. The result is verified by the file on disk — `ok` is only true when a
    non-empty .mvr exists at `path`.

    Two things worth knowing: Vectorworks' file dialog mangles path separators
    in its name field, so only the file NAME is typed and the file is moved to
    `path` afterwards (`saved_to` reports where VW put it, `moved` whether it
    had to be relocated). And the export needs Vectorworks in the foreground —
    this steals focus for a few seconds.

    inspect=true adds a summary of what the file contains (layers, objects,
    meshes, GDTF specs) by reading the ZIP/XML.
    """
    import vwx_gui
    try:
        result = await asyncio.to_thread(vwx_gui.export_mvr, path)
    except vwx_gui.GuiUnavailable as exc:
        return _json({'ok': False, 'error': str(exc)})
    if inspect and result.get('ok'):
        try:
            import mvr_file
            result['mvr'] = mvr_file.inspect(result['path'])
        except Exception as exc:                      # never fail the export
            result['inspect_error'] = str(exc)
    return _json(result)


@vtool
async def import_mvr(ctx: Context, path: str) -> str:
    """Import an MVR file into the front document (drives the VW menu + dialogs).

    Same caveat as export_mvr: the command is not scriptable, so this is real
    input against File ▸ Import ▸ Import MVR...

    Two limits, both reported instead of hidden. Vectorworks' Open dialog does
    not accept typed input from outside the process, so the file is picked from
    the dialog's own current folder — put it there, or finish the dialog by
    hand. And the result is verified by COUNTING the document's objects before
    and after: `ok` is only true when the object count actually grew, because a
    dialog that closes without importing looks exactly like success.
    """
    import vwx_gui

    def count():
        try:
            import json
            raw = cmd("find_objects", {"criteria": "(ALL)", "limit": 1})
            return json.loads(raw).get("count")
        except Exception:
            return None

    before = await asyncio.to_thread(count)
    try:
        result = await asyncio.to_thread(vwx_gui.import_mvr, path)
    except vwx_gui.GuiUnavailable as exc:
        return _json({'ok': False, 'error': str(exc)})
    after = await asyncio.to_thread(count)
    result['objects_before'] = before
    result['objects_after'] = after
    if before is not None and after is not None:
        result['added'] = after - before
        if result.get('ok') and result['added'] <= 0:
            result['ok'] = False
            result['error'] = ('the dialog closed but the document gained no '
                               'objects — nothing was imported')
    return _json(result)


@vtool
def inspect_mvr(ctx: Context, path: str) -> str:
    """Read an MVR file without Vectorworks: provider, version, layers, objects.

    An MVR is a ZIP with GeneralSceneDescription.xml plus one .glb per object.
    Returns the MVR version, the writing application, layer list, scene-object
    and fixture counts, GDTF specs/modes and the object element names actually
    found — so a schema change shows up as data instead of a silent zero.
    """
    import mvr_file
    try:
        return _json(mvr_file.inspect(path))
    except mvr_file.MvrError as exc:
        return _json({'error': str(exc)})


@vtool
async def mvr_dialog(ctx: Context) -> str:
    """Report any MVR dialog currently open (for handing the flow to a GUI agent).

    When the automated flow cannot finish — a different VW version, an extra
    prompt, a folder the caller must choose — this says what is on screen so a
    CUA agent (or a person) can take over: dialog title, readable text and the
    buttons it offers.
    """
    import vwx_gui
    try:
        dialogs = await asyncio.to_thread(vwx_gui.list_dialogs)
    except vwx_gui.GuiUnavailable as exc:
        return _json({'error': str(exc)})
    out = []
    for d in dialogs:
        if 'MVR' in d['title'] or d['title'] in ('Save File', 'Open'):
            out.append({'title': d['title'],
                        'buttons': [c['text'] for c in
                                    await asyncio.to_thread(vwx_gui.dialog_children,
                                                            d['hwnd'])
                                    if c['class'] == 'Button']})
    return _json({'mvr_dialogs': out, 'all_dialogs': [d['title'] for d in dialogs]})
