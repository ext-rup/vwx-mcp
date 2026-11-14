"""Wake watchdog for the file transport — the native palette's job, in Python.

The MCP server talks to Vectorworks through the plugin folder:

    ipc/jobs/<ts>-<cid>.json     the server writes a job here
    ipc/results/<cid>.json       the pump writes the answer here
    ipc/native.alive             "<epoch> <paused 0|1>" heartbeat

The heartbeat and the "wake Vectorworks when a job appears" trigger normally
come from the native palette (BraceWorxsVwxPlg.vlb), which fires the
"VWX Bridge Start" menu command. This script provides both from outside
Vectorworks, so the bridge works on a machine where the native plug-in is not
installed yet (or while developing it):

  * rewrites ipc/native.alive every second (the server answers VW_BRIDGE_DOWN
    immediately when that heartbeat is stale),
  * watches ipc/jobs and bridge.wake and, on a change, brings Vectorworks to the
    front and sends Ctrl+Shift+B with real key input.

Trade-off vs. the native palette: this steals focus for a moment, because a
menu accelerator only fires in the foreground window. The native palette posts
the command straight into Vectorworks instead.

    python bridge/wake_watch.py                 # autodetect the plugin dir
    python bridge/wake_watch.py --plugin-dir "C:/.../Plug-ins/VW-MCP" -v
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)

VK_CONTROL, VK_SHIFT, VK_B = 0x11, 0x10, 0x42
KEYEVENTF_KEYUP = 0x0002


def find_plugin_dir() -> Path | None:
    forced = os.environ.get("VWX_PLUGIN_DIR")
    if forced and Path(forced).is_dir():
        return Path(forced)
    root = Path(os.environ.get("APPDATA", "")) / "Nemetschek" / "Vectorworks"
    if not root.is_dir():
        return None
    versions = sorted((d for d in root.iterdir() if d.is_dir() and len(d.name) == 4
                       and d.name.isdigit()), reverse=True)
    for version in versions:
        for name in ("VW-MCP", "VWX-MCP"):
            cand = version / "Plug-ins" / name
            if cand.is_dir():
                return cand
    return None


def find_vw_window() -> int:
    """Handle of the top-level Vectorworks window, or 0."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "Vectorworks" in title and "Bridge" not in title:
            found.append((hwnd, title))
            return False
        return True

    user32.EnumWindows(enum, 0)
    return found[0][0] if found else 0


def send_start_shortcut(hwnd: int, verbose: bool = False) -> bool:
    """Bring VW to the front and fire Ctrl+Shift+B."""
    if not hwnd:
        hwnd = find_vw_window()
    if not hwnd:
        if verbose:
            print("  no Vectorworks window found", flush=True)
        return False
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.25)
    for vk in (VK_CONTROL, VK_SHIFT):
        user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_B, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(VK_B, 0, KEYEVENTF_KEYUP, 0)
    for vk in (VK_SHIFT, VK_CONTROL):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    if verbose:
        print(f"  sent Ctrl+Shift+B to hwnd {hwnd}", flush=True)
    return True


def pending_jobs(jobs: Path) -> list[Path]:
    if not jobs.is_dir():
        return []
    return sorted(p for p in jobs.glob("*.json") if not p.name.endswith(".tmp"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plugin-dir", help="VW plugin dir (default: autodetect)")
    ap.add_argument("--interval", type=float, default=1.0, help="heartbeat interval (s)")
    ap.add_argument("--once", action="store_true", help="one heartbeat, then exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    plugin = Path(args.plugin_dir) if args.plugin_dir else find_plugin_dir()
    if not plugin or not plugin.is_dir():
        print("error: plugin dir not found — pass --plugin-dir", file=sys.stderr)
        return 2
    ipc = plugin / "ipc"
    jobs, results = ipc / "jobs", ipc / "results"
    jobs.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    alive = ipc / "native.alive"
    wake = plugin / "bridge.wake"

    print(f"wake_watch: plugin dir {plugin}", flush=True)
    seen = {p.name for p in pending_jobs(jobs)}
    # A job that was fired at but never drained is retried: the accelerator only
    # fires in the FOREGROUND window, so a single keystroke is lost whenever the
    # user (or another app) has focus — and then the job sits in the queue
    # forever while the server waits out its timeout. fired_at tracks the last
    # attempt per job; RETRY_AFTER/S and MAX_TRIES bound the retries.
    fired_at = {}
    tries = {}
    reported = set()
    RETRY_AFTER, MAX_TRIES = 4.0, 6
    if seen:
        print(f"  {len(seen)} job(s) already queued — firing once", flush=True)
        send_start_shortcut(0, args.verbose)
        now = time.time()
        for name in seen:
            fired_at[name] = now
            tries[name] = 1
    wake_mtime = wake.stat().st_mtime if wake.exists() else 0.0
    beat_fail = 0

    while True:
        tmp = alive.with_suffix(".tmp")
        try:
            tmp.write_text(f"{time.time():.3f} 0", encoding="utf-8")
            os.replace(tmp, alive)
            beat_fail = 0
        except Exception as exc:                      # pragma: no cover
            # A reader can hold native.alive open WITHOUT FILE_SHARE_DELETE
            # (Vectorworks' native plug-in does), which makes the atomic replace
            # fail with Access denied. The reader only looks at the mtime, so
            # writing in place is fine — a torn read of a 20-byte file is not a
            # real risk, and the alternative is a dead heartbeat, after which
            # the server refuses every job with VW_BRIDGE_DOWN.
            try:
                alive.write_text(f"{time.time():.3f} 0", encoding="utf-8")
                beat_fail = 0
            except Exception:
                beat_fail += 1
                if beat_fail in (1, 60):              # once, then once a minute
                    print(f"  heartbeat failed ({beat_fail}x): {exc}", flush=True)

        if wake.exists():
            mtime = wake.stat().st_mtime
            if mtime != wake_mtime:
                wake_mtime = mtime
                print("wake file touched — firing", flush=True)
                send_start_shortcut(0, args.verbose)

        current = pending_jobs(jobs)
        names = {p.name for p in current}
        new = [p for p in current if p.name not in seen]
        if new:
            print(f"job {new[0].name} (+{len(new) - 1} more) — firing", flush=True)
            send_start_shortcut(0, args.verbose)
            now = time.time()
            for p in new:
                seen.add(p.name)
                fired_at[p.name] = now
                tries[p.name] = 1
        else:
            # Still queued after a fire attempt: the keystroke did not land.
            now = time.time()
            stuck = [n for n in names
                     if now - fired_at.get(n, 0) > RETRY_AFTER
                     and tries.get(n, 0) < MAX_TRIES]
            if stuck:
                for n in stuck:
                    tries[n] = tries.get(n, 0) + 1
                    fired_at[n] = now
                print(f"job {stuck[0]} still queued — refiring "
                      f"({tries[stuck[0]]}/{MAX_TRIES})", flush=True)
                send_start_shortcut(0, args.verbose)
            else:
                for n in names:
                    if tries.get(n, 0) >= MAX_TRIES and n not in reported:
                        reported.add(n)
                        print(f"  giving up on {n} after {MAX_TRIES} tries — "
                              "is Vectorworks running and the menu command "
                              "assigned (Ctrl+Shift+B)?", flush=True)
        seen &= names                                 # forget drained jobs
        for gone in [n for n in fired_at if n not in names]:
            fired_at.pop(gone, None)
            tries.pop(gone, None)

        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
