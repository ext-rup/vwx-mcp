"""Native GUI automation for the commands Vectorworks will not run headless.

WHY THIS EXISTS
---------------
MVR import/export has **no `vs.*` surface at all** on VW2027: the SDK index has
zero GDTF/MVR functions, and `DoMenuTextByName('Export MVR', 0)` raises a
Vectorworks script error instead of running the command (verified 2026-11-14 —
the menu item is not scriptable, like the other export commands). The only route
is the menu, so this module drives the menu and its dialogs the way a person
would.

INPUT MUST BE REAL
------------------
Vectorworks' BCG widgets hit-test the PHYSICAL cursor and read the live keyboard
state (`GetKeyState`), so posted messages (PostMessage/WM_KEYDOWN) never open a
menu and never fire a shortcut. Everything here uses `keybd_event` and
`mouse_event`, and the native file dialog gets `WM_SETTEXT` — which works,
because that one is a real Win32 control (see `bridge/gui_*.ps1`, the PowerShell
originals of the same trick).

PLATFORM
--------
Windows only. macOS has no equivalent here yet; every entry point raises
`GuiUnavailable` with a message that says so, rather than pretending.
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

IS_WINDOWS = sys.platform == 'win32'

if IS_WINDOWS:
    _u = ctypes.windll.user32
    _u.SetProcessDPIAware()
else:                                   # pragma: no cover - no Mac here
    _u = None

WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
SW_RESTORE = 9

VK = {
    'alt': 0x12, 'ctrl': 0x11, 'shift': 0x10, 'enter': 0x0D, 'esc': 0x1B,
    'escape': 0x1B, 'down': 0x28, 'up': 0x26, 'right': 0x27, 'left': 0x25,
    'tab': 0x09, 'delete': 0x2E, 'backspace': 0x08, 'space': 0x20,
}

# Where the MVR commands sit in the menu, counted from the top of the File menu
# with separators ignored (VW2027, English UI, Spotlight workspace):
#   File: 1 New, 2 Open, 3 Open Project Sharing Server File, 4 Open Recent,
#         5 Close, 6 Close All, 7 Save, 8 Save As, 9 Save a Copy as, 10 Save All,
#         11 Save as Template, 12 Revert to Last Saved Version, 13 Batch Convert,
#         14 Send to Cinema 4D, 15 Send to Vision, 16 Document Settings,
#         17 Project Sharing, 18 Save and Commit, 19 Close and Release,
#         20 Refresh, 21 Revert, 22 Import, 23 Export, ...
#   Export submenu: 1 DXF/DWG, 2 DWF, 3 IFC Project, 4 Revit, 5 ASCII Patch,
#         6 Lighting Device Data, 7 MVR, ...
#   Import submenu: 1 Import Single DXF/DWG, 2 Import Single DWF,
#         3 Import DXF/DWG or DWF, 4 Import IFC, 5 Import Revit,
#         6 Import Revit (Batch), 7 Import Lighting Device Data, 8 Import GDTF,
#         9 Import MVR, ...
# These are ITEM NUMBERS (1-based, separators ignored), not key counts: opening
# a menu selects its first item, so reaching item N takes N-1 Down presses.
# The numbers are only a route: every caller VERIFIES the dialog title that
# appears, so a reordered menu fails loudly instead of exporting something else.
FILE_EXPORT_ITEM = 23
EXPORT_MVR_ITEM = 7
FILE_IMPORT_ITEM = 22
IMPORT_MVR_ITEM = 9

EXPORT_DIALOG = 'Export MVR File'
# Import MVR has no options dialog: the menu item goes straight to the file
# picker. (Export does have one — that is the asymmetry.)
IMPORT_DIALOG = 'Open File'
SAVE_DIALOG = 'Save File'
OPEN_DIALOG = 'Open File'
VW_MESSAGE = 'Vectorworks'


class GuiUnavailable(RuntimeError):
    """The host cannot drive the GUI (wrong platform, or VW is not running)."""


def _require():
    if not IS_WINDOWS:
        raise GuiUnavailable(
            'GUI automation is Windows-only in this fork; on macOS the MVR '
            'commands have no driver yet. Run the menu command by hand or '
            'extend vwx_gui.py for the Mac.')
    if _u is None:
        raise GuiUnavailable('user32 not available')


# ── window helpers ────────────────────────────────────────────────────────

def _text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    _u.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _cls(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _u.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _top_windows():
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _l):
        out.append(h)
        return True

    _u.EnumWindows(cb, 0)
    return out


def find_vw_window():
    """The Vectorworks main frame (class starts with 'Afx:' and has a title)."""
    _require()
    for h in _top_windows():
        if _cls(h).startswith('Afx:') and 'Vectorworks' in _text(h):
            return h
    return None


def list_dialogs():
    """Visible #32770 dialogs, as [{hwnd, title, class}]."""
    _require()
    out = []
    for h in _top_windows():
        if _cls(h) == '#32770' and _u.IsWindowVisible(h):
            out.append({'hwnd': h, 'title': _text(h), 'class': _cls(h)})
    return out


def dialog_children(hwnd):
    """Child controls, as [{hwnd, class, id, text}] (one level deep)."""
    _require()
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _l):
        out.append({'hwnd': h, 'class': _cls(h),
                    'id': _u.GetDlgCtrlID(h), 'text': _text(h)})
        return True

    _u.EnumChildWindows(hwnd, cb, 0)
    return out


def _buttons(hwnd):
    return [c['text'].replace('&', '').strip()
            for c in dialog_children(hwnd) if c['class'] == 'Button']


def find_dialog(title, timeout=10.0, want_button=None):
    """Wait for a visible dialog with this exact title; None on timeout.

    `want_button` disambiguates: Vectorworks sometimes has two windows with the
    same title (a wrapper and the real Explorer dialog), and only one of them
    carries the button the caller is about to press. Matching on the button is
    the difference between "no Save button" and a saved file.
    """
    _require()
    deadline = time.time() + timeout
    fallback = None
    while time.time() < deadline:
        for d in list_dialogs():
            if d['title'] != title:
                continue
            if want_button is None:
                return d['hwnd']
            if want_button.lower() in [b.lower() for b in _buttons(d['hwnd'])]:
                return d['hwnd']
            fallback = fallback or d['hwnd']
        time.sleep(0.2)
    return fallback


def wait_closed(hwnd, timeout=15.0):
    _require()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _u.IsWindow(hwnd):
            return True
        time.sleep(0.2)
    return False


# ── input ─────────────────────────────────────────────────────────────────

def _tap(vk, hold=0.04, gap=0.06):
    scan = _u.MapVirtualKeyW(vk, 0)
    _u.keybd_event(vk, scan, 0, 0)
    time.sleep(hold)
    _u.keybd_event(vk, scan, 2, 0)
    time.sleep(gap)


def focus(hwnd):
    _require()
    if _u.IsIconic(hwnd):
        _u.ShowWindow(hwnd, SW_RESTORE)
    _u.SetForegroundWindow(hwnd)
    time.sleep(0.4)


def send_keys(seq):
    """Send a key sequence: ints/names, or an int as a repeat count.

    ['alt+f', 22, 'right', 6, 'enter'] -> Alt+F, 22x Down, Right, 6x Down, Enter
    """
    _require()
    for item in seq:
        if isinstance(item, int):
            for _ in range(item):
                _tap(VK['down'])
            continue
        combo = str(item).lower().split('+')
        mods = [m for m in combo[:-1] if m in VK]
        key = combo[-1]
        vk = VK.get(key)
        if vk is None:
            if len(key) != 1:
                raise ValueError('unknown key %r' % item)
            vk = ord(key.upper())
        for m in mods:
            _u.keybd_event(VK[m], _u.MapVirtualKeyW(VK[m], 0), 0, 0)
            time.sleep(0.04)
        _tap(vk)
        for m in reversed(mods):
            _u.keybd_event(VK[m], _u.MapVirtualKeyW(VK[m], 0), 2, 0)
            time.sleep(0.04)
        time.sleep(0.15)


def _vk_for_char(ch):
    """(vk, needs_shift) for a character, via the keyboard layout."""
    res = _u.VkKeyScanW(ord(ch))
    if res == -1:
        return None, False
    return res & 0xFF, bool(res & 0x100)


def type_text(text, delay=0.012):
    """Type literal text with real keystrokes (keybd_event).

    Not WM_SETTEXT: a file dialog does not just store what you put in its name
    field, it parses it. Setting a full path with WM_SETTEXT made VW2027 turn
    every backslash into a literal 'ß' and save the file next to the Desktop
    (verified 2026-11-14) — real keystrokes make the dialog navigate instead.
    """
    _require()
    for ch in text:
        vk, shift = _vk_for_char(ch)
        if vk is None:
            continue
        if shift:
            _u.keybd_event(VK['shift'], _u.MapVirtualKeyW(VK['shift'], 0), 0, 0)
            time.sleep(0.01)
        _u.keybd_event(vk, _u.MapVirtualKeyW(vk, 0), 0, 0)
        time.sleep(delay)
        _u.keybd_event(vk, _u.MapVirtualKeyW(vk, 0), 2, 0)
        if shift:
            _u.keybd_event(VK['shift'], _u.MapVirtualKeyW(VK['shift'], 0), 2, 0)
        time.sleep(delay)


def click_at(x, y):
    """Real mouse click at physical screen coordinates."""
    _require()
    _u.SetCursorPos(int(x), int(y))
    time.sleep(0.1)
    _u.mouse_event(0x0002, 0, 0, 0, 0)          # LEFTDOWN
    time.sleep(0.05)
    _u.mouse_event(0x0004, 0, 0, 0, 0)          # LEFTUP
    time.sleep(0.15)


def click_control(hwnd):
    """Click the centre of a control with the real cursor."""
    _require()
    r = wt.RECT()
    _u.GetWindowRect(hwnd, ctypes.byref(r))
    click_at((r.left + r.right) // 2, (r.top + r.bottom) // 2)


def press_button(dlg, label):
    """Click a button of a dialog by its text (BM_CLICK, no cursor needed).

    PostMessage, not SendMessage: Vectorworks' buttons are owner-drawn and a
    synchronous BM_CLICK can block until the dialog closes, which is exactly
    what the caller is waiting to observe.
    """
    _require()
    want = label.replace('&', '').strip().lower()
    for c in dialog_children(dlg):
        if c['class'] != 'Button':
            continue
        if c['text'].replace('&', '').strip().lower() != want:
            continue
        if not _u.IsWindowVisible(c['hwnd']):
            continue
        _u.PostMessageW(c['hwnd'], BM_CLICK, 0, 0)
        return True
    return False


def set_filename(dlg, path):
    """Put a full path into a native file dialog's name field.

    The modern Explorer dialog keeps the name in an `Edit` with control id
    1001 inside a DirectUIHWND; WM_SETTEXT works there because it is a real
    Win32 edit, unlike Vectorworks' own controls.
    """
    _require()
    edits = [c for c in dialog_children(dlg)
             if c['class'] == 'Edit' and c['id'] == 1001]
    if not edits:
        edits = [c for c in dialog_children(dlg) if c['class'] == 'Edit']
    if not edits:
        return False
    for e in edits:
        _u.SendMessageW(e['hwnd'], WM_SETTEXT, 0, ctypes.c_wchar_p(path))
    time.sleep(0.3)
    return True


EM_SETSEL = 0x00B1


def type_filename(dlg, name):
    """Replace the file dialog's name field with `name` (real input).

    `name` must be a BARE FILE NAME. Vectorworks' file dialog mangles path
    separators — a full path typed or written into that field comes out as
    'C:ßUsersßmaximß…' and the file is saved with those characters in its name
    (verified 2026-11-14). The folder is whatever the dialog currently shows,
    so the caller moves the file afterwards (see export_mvr).
    """
    _require()
    edits = [c for c in dialog_children(dlg)
             if c['class'] == 'Edit' and c['id'] == 1001]
    if not edits:
        edits = [c for c in dialog_children(dlg) if c['class'] == 'Edit']
    if not edits:
        return False
    edit = edits[0]['hwnd']
    click_control(edit)
    _u.SendMessageW(edit, EM_SETSEL, 0, -1)     # select all, then type over it
    time.sleep(0.15)
    type_text(name)
    time.sleep(0.2)
    return True


def _find_saved(name, extra_dirs=(), timeout=20.0):
    """Locate a file Vectorworks just wrote, by name, in the likely folders.

    The save dialog decides the folder, and it cannot be steered from here, so
    the file is found afterwards: the requested folder, the document's folder,
    the usual user folders, then a bounded walk of the profile.
    """
    name = os.path.basename(name)
    here = os.getcwd()
    cands = [d for d in extra_dirs if d] + [
        os.path.dirname(os.path.abspath(name)) or here,
        os.path.join(os.path.expanduser('~'), 'Desktop'),
        os.path.join(os.path.expanduser('~'), 'Documents'),
        os.path.expanduser('~'),
        here,
    ]
    deadline = time.time() + timeout
    seen = set()
    while time.time() < deadline:
        for d in cands:
            p = os.path.join(d, name)
            if p in seen:
                continue
            seen.add(p)
            if os.path.isfile(p):
                return p
        time.sleep(0.4)
    # last resort: a bounded walk of the profile
    root = os.path.expanduser('~')
    for base, dirs, files in os.walk(root):
        if base.count(os.sep) - root.count(os.sep) > 4:
            dirs[:] = []
            continue
        if name in files:
            return os.path.join(base, name)
    return None


# ── the MVR flows ─────────────────────────────────────────────────────────

def _menu_popups():
    """Visible untitled Afx popups — Vectorworks' own menus (#32768 is not used).

    VW draws its menus with MFC/BCG, so a menu is an untitled 'Afx:...' window,
    not a standard Win32 menu. That is also why GetMenuString cannot be used to
    find an item by name and the route is counted arrow presses instead.
    """
    out = []
    for h in _top_windows():
        if _cls(h).startswith('Afx:') and _u.IsWindowVisible(h) and not _text(h):
            out.append(h)
    return out


def _wait_popups(count, timeout=2.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(_menu_popups()) >= count:
            return True
        time.sleep(0.1)
    return False


def _open_menu_command(file_index, sub_index, expect_title, timeout=12.0):
    """File ▸ <item at file_index> ▸ <item at sub_index>, then wait for a dialog.

    Returns (hwnd, None) on success or (None, reason) — never guesses. The menu
    is verified at each step (a popup must appear, then a second one for the
    submenu) because a swallowed keystroke otherwise leaves the flow waiting
    for a dialog that will never come.
    """
    vw = find_vw_window()
    if not vw:
        return None, 'no Vectorworks window found'
    for attempt in (1, 2):
        send_keys(['escape'])          # a menu left open from before eats Alt+F
        time.sleep(0.3)
        focus(vw)
        send_keys(['alt+f'])
        if not _wait_popups(1):
            continue
        # -1: the menu opens with its first item already selected.
        send_keys([file_index - 1])
        send_keys(['right'])
        if not _wait_popups(2):
            send_keys(['escape'])
            continue
        send_keys([sub_index - 1, 'enter'])
        hwnd = find_dialog(expect_title, timeout)
        if hwnd:
            return hwnd, None
        send_keys(['escape'])
    seen = [d['title'] for d in list_dialogs()]
    return None, ('the %r dialog did not appear (visible dialogs: %s) — the menu '
                  'layout may differ from the one this module was written for'
                  % (expect_title, seen or 'none'))


def export_mvr(path, timeout=20.0):
    """Export the front document to an MVR file, verified by the file on disk.

    Returns a dict; `ok` is only true when the file exists and is non-empty.
    """
    _require()
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        return {'ok': False, 'error': 'target folder does not exist: %s' % folder}
    if os.path.exists(path):
        os.remove(path)                 # so "exists" below proves this run wrote it

    dlg, err = _open_menu_command(FILE_EXPORT_ITEM, EXPORT_MVR_ITEM, EXPORT_DIALOG)
    if not dlg:
        return {'ok': False, 'stage': 'menu', 'error': err}

    # The Export MVR dialog: defaults are "All objects in drawing" + all object
    # types, which is what an MVR exchange wants. OK moves on to the file dialog.
    if not press_button(dlg, 'OK'):
        return {'ok': False, 'stage': 'options',
                'error': 'no OK button on the %r dialog' % EXPORT_DIALOG,
                'buttons': [c['text'] for c in dialog_children(dlg)
                            if c['class'] == 'Button']}
    save = find_dialog(SAVE_DIALOG, timeout, want_button='Save')
    if not save:
        return {'ok': False, 'stage': 'save-dialog',
                'error': 'the Save File dialog did not appear',
                'dialogs': [d['title'] for d in list_dialogs()]}
    base = os.path.basename(path)
    if not type_filename(save, base):
        return {'ok': False, 'stage': 'filename',
                'error': 'no filename edit in the Save File dialog'}
    if not press_button(save, 'Save'):
        return {'ok': False, 'stage': 'save',
                'error': 'no Save button in the Save File dialog'}
    wait_closed(save, timeout)
    written = _find_saved(base, [folder], timeout)
    if not written:
        return {'ok': False, 'stage': 'verify',
                'error': ('Vectorworks reported no error but %r was not found '
                          'in the expected folders' % base),
                'dialogs': [d['title'] for d in list_dialogs()]}
    moved = False
    if os.path.abspath(written) != path:
        # The dialog chose the folder; put the file where the caller asked.
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            os.replace(written, path)
            moved = True
        except OSError as exc:
            size = os.path.getsize(written)
            return {'ok': size > 0, 'path': written, 'bytes': size,
                    'requested_path': path, 'moved': False,
                    'warning': 'saved to %s but could not be moved: %s'
                               % (written, exc)}
    size = os.path.getsize(path)
    return {'ok': size > 0, 'path': path, 'bytes': size,
            'saved_to': written, 'moved': moved,
            'error': None if size else 'the exported file is empty'}


def import_mvr(path, timeout=30.0):
    """Import an MVR file into the front document.

    Honest about what it can and cannot do (verified 2026-11-14):

    * The menu route and the file dialog work.
    * Vectorworks' Open dialog does NOT accept typed input from outside the
      process — the name field stays empty however the keystrokes are sent —
      so the file is selected from the dialog's CURRENT FOLDER by name. Put the
      file there, or complete the dialog by hand / with a GUI agent.
    * Vectorworks' own verdict is returned in `message`: an MVR that contains
      only ConnectCAD scene objects round-trips to "could not find any data to
      load", because the importer consumes fixtures and trusses.
    """
    _require()
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return {'ok': False, 'error': 'no such file: %s' % path}

    dlg, err = _open_menu_command(FILE_IMPORT_ITEM, IMPORT_MVR_ITEM, IMPORT_DIALOG)
    if not dlg:
        return {'ok': False, 'stage': 'menu', 'error': err}
    if not type_filename(dlg, os.path.basename(path)):
        return {'ok': False, 'stage': 'filename',
                'error': 'no filename edit in the Open dialog',
                'dialog': dlg}
    if not press_button(dlg, 'Open'):
        return {'ok': False, 'stage': 'open',
                'error': 'no Open button in the Open dialog', 'dialog': dlg}

    # The file dialog closes first and Vectorworks' verdict comes AFTER it, so
    # keep watching for a message box once the dialog is gone: that message is
    # the real result ("could not find any data to load" is a refusal, not a
    # success), and missing it makes a failed import look like a good one.
    deadline = time.time() + timeout
    closed_at = None
    while time.time() < deadline:
        for d in list_dialogs():
            if d['title'] != VW_MESSAGE:
                continue
            text = ' '.join(c['text'] for c in dialog_children(d['hwnd'])
                            if c['class'] in ('Static', 'Edit')).strip()
            press_button(d['hwnd'], 'OK')
            return {'ok': False, 'stage': 'import',
                    'path': path, 'message': text,
                    'error': 'Vectorworks refused the file (see message)'}
        if not _u.IsWindow(dlg):
            if closed_at is None:
                closed_at = time.time()
            elif time.time() - closed_at > 6.0:
                break
        time.sleep(0.3)
    closed = not _u.IsWindow(dlg)
    return {'ok': bool(closed), 'path': path,
            'error': None if closed else 'the Open dialog is still up',
            'folder': 'the dialog picks the file from its own current folder',
            'verified': 'dialog closed; check the document for the imported objects'}
