"""Dragon process lifecycle monitor — auto-disconnect/reconnect.

Uses Win32 named events so the launcher's pump (MsgWaitForMultipleObjects)
wakes instantly when Dragon exits or reappears — no polling delay.

The monitor thread detects Dragon exit/restart but does NOT call
natConnect/natDisconnect directly — COM objects are owned by the
main thread.
"""

import ctypes
import ctypes.wintypes as wt
import logging
import time

from ._win32 import user32, kernel32, DRAGON_CLS

log = logging.getLogger("natlink.compat")

SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102

# Win32 event names — the launcher adds these to its pump wait array
_DRAGON_EXITED_EVENT = "NatlinkDragonExited"
_DRAGON_REAPPEARED_EVENT = "NatlinkDragonReappeared"

# Win32 event handles (created once per session)
_h_dragon_exited = 0
_h_dragon_reappeared = 0


def create_events():
    """Create the Win32 events. Returns (h_exited, h_reappeared)."""
    global _h_dragon_exited, _h_dragon_reappeared
    if not _h_dragon_exited:
        _h_dragon_exited = kernel32.CreateEventW(None, True, False, _DRAGON_EXITED_EVENT)
    if not _h_dragon_reappeared:
        _h_dragon_reappeared = kernel32.CreateEventW(None, True, False, _DRAGON_REAPPEARED_EVENT)
    return _h_dragon_exited, _h_dragon_reappeared


def close_events():
    """Close the Win32 events."""
    global _h_dragon_exited, _h_dragon_reappeared
    if _h_dragon_exited:
        kernel32.CloseHandle(_h_dragon_exited)
        _h_dragon_exited = 0
    if _h_dragon_reappeared:
        kernel32.CloseHandle(_h_dragon_reappeared)
        _h_dragon_reappeared = 0


def _signal_exited():
    if _h_dragon_exited:
        kernel32.SetEvent(_h_dragon_exited)


def _signal_reappeared():
    if _h_dragon_reappeared:
        kernel32.SetEvent(_h_dragon_reappeared)


def _get_dragon_handle():
    """Get a waitable process handle for Dragon, or None."""
    hwnd = user32.FindWindowW(DRAGON_CLS, None)
    if not hwnd:
        return None
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    return kernel32.OpenProcess(SYNCHRONIZE, False, pid.value)


def start_dragon_monitor(state):
    """Start a daemon thread that watches Dragon's lifecycle.

    Signals Win32 events so the launcher's pump wakes instantly.
    """
    import threading
    stop_event = state.monitor_stop_event

    # Reset events
    if _h_dragon_exited:
        kernel32.ResetEvent(_h_dragon_exited)
    if _h_dragon_reappeared:
        kernel32.ResetEvent(_h_dragon_reappeared)

    def _monitor():
        log.info("Dragon monitor started")
        while not stop_event.is_set():
            if state.connected:
                handle = _get_dragon_handle()
                if not handle:
                    if state.connected:
                        log.debug("Dragon process gone")
                        _signal_exited()
                    stop_event.wait(2)
                    continue
                try:
                    while not stop_event.is_set():
                        rc = kernel32.WaitForSingleObject(handle, 500)
                        if rc != WAIT_TIMEOUT:
                            if state.connected:
                                log.debug("Dragon process exited")
                                _signal_exited()
                            break
                        if not user32.FindWindowW(DRAGON_CLS, None):
                            if state.connected:
                                log.debug("Dragon window closed")
                                _signal_exited()
                            break
                finally:
                    kernel32.CloseHandle(handle)
            else:
                if user32.FindWindowW(DRAGON_CLS, None):
                    log.info("Dragon detected")
                    _signal_reappeared()
                    for _ in range(60):
                        if state.connected or stop_event.is_set():
                            break
                        time.sleep(1)
                else:
                    stop_event.wait(2)

    t = threading.Thread(target=_monitor, daemon=True, name="dragon-monitor")
    state.set_monitor_thread(t)
    t.start()
