"""Natlink launcher primitives — low-level COM probing, event hooks, mutex.

High-level orchestration (run(), restart) lives in natlink_compat._orchestrator.

This module provides:
  - COM readiness probing (replaces blind sleep)
  - Wait-for-Dragon via SetWinEventHook (zero polling)
  - Profile-ready detection via Dragon log monitoring
  - Single instance mutex
  - Shutdown/restart event signaling
"""

import ctypes
import ctypes.wintypes as wt
import logging
import os
import re
import sys
import time
from pathlib import Path

from ._com_helpers import release_raw
from ._connection import CLSCTX_LOCAL_SERVER  # also sets ole32.CoCreateInstance argtypes
from ._win32 import user32, kernel32, DRAGON_CLS

log = logging.getLogger("natlink.com.launcher")


ole32 = ctypes.windll.ole32

_PROFILE_READY_RE = re.compile(r"Normal mode: You can dictate", re.IGNORECASE)


# WinEventProc callback type (module-level to avoid recreating each call)
_WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wt.HANDLE, wt.DWORD, wt.HWND,
    ctypes.c_long, ctypes.c_long, wt.DWORD, wt.DWORD)


# ---------------------------------------------------------------------------
# COM readiness probing
# ---------------------------------------------------------------------------

def _wait_for_com_ready(max_wait=30, initial_delay=0.5):
    """Retry CoCreateInstance(DgnSite) until Dragon's COM server responds.

    Dragon's toolbar window appears several seconds before its COM
    server accepts connections.  Probes with exponential backoff
    (0.5s, 1s, 2s, ...) capped at 4s per retry.

    Uses pump() between retries so the STA message loop stays responsive
    (UI thread's run_on_ui_thread and Dragon callbacks aren't blocked).
    """
    from ._guids import CLSID_DgnSite, IID_IUnknown
    from ._pump import pump

    delay = initial_delay
    deadline = time.monotonic() + max_wait

    # Temporary event handle for pump() — never signaled, just used for
    # timed message dispatch.
    h_wait = kernel32.CreateEventW(None, True, False, None)

    try:
        while time.monotonic() < deadline:
            ppv = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_DgnSite), None, CLSCTX_LOCAL_SERVER,
                ctypes.byref(IID_IUnknown), ctypes.byref(ppv))
            if hr >= 0:
                if ppv.value:
                    release_raw(ppv)
                log.debug("Dragon COM ready after probe")
                return True
            log.debug("COM probe hr=0x%08X, retry in %.1fs", hr & 0xFFFFFFFF, delay)
            # Pump messages while waiting — keeps STA responsive
            pump(h_event=h_wait, timeout_ms=int(delay * 1000))
            delay = min(delay * 2, 4.0)
    finally:
        kernel32.CloseHandle(h_wait)

    log.warning("COM readiness probe timed out after %ds — connecting anyway", max_wait)
    return False


# ---------------------------------------------------------------------------
# Wait for Dragon window (SetWinEventHook — zero polling)
# ---------------------------------------------------------------------------

def _wait_for_dragon_window(h_shutdown=None, h_restart=None):
    """Block until Dragon's main window appears or shutdown is signaled.

    Uses SetWinEventHook with EVENT_OBJECT_CREATE for zero-polling
    notification.  Falls back to FindWindowW polling if the hook fails.

    If h_restart is signaled while waiting, Dragon is launched.

    Returns True if Dragon was found, False if shutdown was requested.
    """
    if user32.FindWindowW(DRAGON_CLS, None):
        return True

    EVENT_OBJECT_CREATE = 0x8000
    WINEVENT_OUTOFCONTEXT = 0x0000
    OBJID_WINDOW = 0

    found_event = kernel32.CreateEventW(None, True, False, None)
    if not found_event:
        return _poll_for_dragon_window(h_shutdown, h_restart)

    def _on_event(hHook, event, hwnd, idObject, idChild, dwThread, dwTime):
        if event == EVENT_OBJECT_CREATE and idObject == OBJID_WINDOW and hwnd:
            buf = ctypes.create_unicode_buffer(256)
            if user32.GetClassNameW(hwnd, buf, 256) and buf.value == DRAGON_CLS:
                kernel32.SetEvent(found_event)

    callback = _WINEVENTPROC(_on_event)

    hook = user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE,
        None, callback, 0, 0, WINEVENT_OUTOFCONTEXT)

    if not hook:
        log.warning("SetWinEventHook failed, falling back to polling")
        kernel32.CloseHandle(found_event)
        return _poll_for_dragon_window(h_shutdown, h_restart)

    # Build handle array: [found_event, h_shutdown?, h_restart?]
    handles = [found_event]
    _FOUND_IDX = 0
    _SHUTDOWN_IDX = None
    _RESTART_IDX = None
    if h_shutdown:
        _SHUTDOWN_IDX = len(handles)
        handles.append(h_shutdown)
    if h_restart:
        _RESTART_IDX = len(handles)
        handles.append(h_restart)
    n_handles = len(handles)
    h_array = (ctypes.c_void_p * n_handles)(*handles)

    try:
        QS_ALLINPUT = 0x04FF
        msg = wt.MSG()
        while True:
            rc = user32.MsgWaitForMultipleObjects(
                n_handles, h_array, False, 2000, QS_ALLINPUT)
            if rc == _FOUND_IDX:
                return True
            if _SHUTDOWN_IDX is not None and rc == _SHUTDOWN_IDX:
                return False
            if _RESTART_IDX is not None and rc == _RESTART_IDX:
                log.info("Restart event signaled while waiting — launching Dragon")
                from ._dragon import launch
                launch()
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if user32.FindWindowW(DRAGON_CLS, None):
                return True
    finally:
        user32.UnhookWinEvent(hook)
        kernel32.CloseHandle(found_event)


def _poll_for_dragon_window(h_shutdown=None, h_restart=None):
    """Fallback: poll FindWindowW every 2 seconds.

    Returns True if Dragon was found, False if shutdown was requested.
    """
    while not user32.FindWindowW(DRAGON_CLS, None):
        if h_shutdown and kernel32.WaitForSingleObject(h_shutdown, 0) == 0:
            return False
        if h_restart and kernel32.WaitForSingleObject(h_restart, 0) == 0:
            log.info("Restart event signaled while polling — launching Dragon")
            from ._dragon import launch
            launch()
        time.sleep(2)
    return True


# ---------------------------------------------------------------------------
# Wait for Dragon profile to be loaded (via log monitoring)
# ---------------------------------------------------------------------------

def _wait_for_profile_via_log(max_wait=30):
    """Wait for Dragon to fully load the profile by monitoring its log.

    Watches Dragon's log for 'updateModesMenu ... Normal mode' which
    signals the profile is loaded and Dragon is ready for voice commands.
    """
    try:
        from ._config import load_config
        cfg = load_config()
        version = cfg.get("dragon", "version", fallback="16")
    except Exception:
        version = "16"

    log_dir = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Nuance" / f"NaturallySpeaking{version}" / "logs"
    if not log_dir.is_dir():
        log.debug("Dragon log dir not found: %s", log_dir)
        return False

    dragon_log = None
    for entry in log_dir.iterdir():
        candidate = entry / "Dragon.log"
        if candidate.is_file():
            dragon_log = candidate
            break
    if not dragon_log:
        log.debug("Dragon.log not found in %s", log_dir)
        return False

    try:
        start_pos = dragon_log.stat().st_size
    except OSError:
        start_pos = 0

    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        time.sleep(0.5)
        try:
            size = dragon_log.stat().st_size
            if size <= start_pos:
                continue
            with open(dragon_log, "r", encoding="utf-8", errors="replace") as f:
                f.seek(start_pos)
                new_content = f.read()
            start_pos = size  # advance so we don't re-read
            if _PROFILE_READY_RE.search(new_content):
                log.info("Dragon log: profile ready (Normal mode detected)")
                return True
        except Exception:
            pass

    log.debug("Dragon log: no Normal mode signal after %ds", max_wait)
    return False



def signal_restart():
    """Signal the launcher's main loop to restart Dragon.

    Called from the tray menu's worker thread. The actual restart
    runs on the main thread which owns the COM objects.
    """
    h = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, _RESTART_EVENT_NAME)
    if h:
        kernel32.SetEvent(h)
        kernel32.CloseHandle(h)
        log.info("Restart event signaled")
        return True
    log.warning("Could not open restart event — launcher not running?")
    return False


# ---------------------------------------------------------------------------
# Shutdown / single instance
# ---------------------------------------------------------------------------

_MUTEX_NAME = "NatlinkLauncherMutex"
_SHUTDOWN_EVENT_NAME = "NatlinkShutdown"
_RESTART_EVENT_NAME = "NatlinkRestartDragon"
_EVENT_MODIFY_STATE = 0x0002
_instance_mutex = None  # prevent GC of mutex handle


def request_shutdown(timeout_ms=5000):
    """Signal the launcher to shut down cleanly.

    Returns True if the shutdown event was signaled (and, for external
    callers, the launcher exited within timeout_ms).
    Returns False if no launcher is running.
    """
    h = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, _SHUTDOWN_EVENT_NAME)
    if not h:
        return False
    kernel32.SetEvent(h)
    kernel32.CloseHandle(h)

    # If called from inside the launcher process (tray Exit menu),
    # don't poll — the main loop handles cleanup after we return.
    if _instance_mutex is not None:
        return True

    # External caller (e.g., `natlink stop`) — wait for the launcher to exit.
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        mutex = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
        err = ctypes.get_last_error()
        if err != 183:  # not ERROR_ALREADY_EXISTS — launcher exited
            kernel32.CloseHandle(mutex)
            return True
        kernel32.CloseHandle(mutex)
        time.sleep(0.2)
    return False


def _acquire_single_instance():
    """Ensure only one launcher runs. Stores mutex handle as module global."""
    global _instance_mutex
    _instance_mutex = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        print("Natlink is already running.")
        sys.exit(0)



