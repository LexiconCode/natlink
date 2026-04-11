"""Launcher orchestration — composable steps for the natlink lifecycle.

Each step can be called independently for pluggable orchestration.
``run()`` calls them in the standard sequence. Third parties can
recompose by calling individual steps or overriding the entry point.

Dependency direction: natlink_compat → natlink_com (never reversed).

UI provider discovery:
  The orchestrator discovers a single UI provider via the
  ``natlink.ui_provider`` entry point group. Non-default providers take
  precedence over the shipping ``default`` entry. If no provider loads,
  it falls back to ``natlink_ui.UIProvider``.
"""

import ctypes
import gc
import logging
import sys
import threading
import time
from pathlib import Path

from natlink_com._launcher import (
    _wait_for_com_ready, _wait_for_dragon_window, _wait_for_profile_via_log,
    _acquire_single_instance,
    _SHUTDOWN_EVENT_NAME, _RESTART_EVENT_NAME,
)
from natlink_com._win32 import kernel32

log = logging.getLogger("natlink.compat.launcher")

ole32 = ctypes.windll.ole32


# ---------------------------------------------------------------------------
# UI provider discovery
# ---------------------------------------------------------------------------

def _discover_ui_provider():
    """Discover a single UI provider via entry points, or fall back to natlink_ui."""
    try:
        from importlib.metadata import entry_points
        eps = list(entry_points(group="natlink.ui_provider"))
    except Exception:
        eps = []

    eps.sort(key=lambda ep: (ep.name == "default", ep.name))

    for ep in eps:
        try:
            provider = ep.load()()
            log.info("UI provider: %s (from %s)", ep.name, ep.value)
            return provider
        except Exception:
            log.warning("Failed to load UI provider %r", ep.name, exc_info=True)

    try:
        from natlink_ui import UIProvider as DefaultUI
        provider = DefaultUI()
        log.info("UI provider: natlink_ui (direct import fallback)")
        return provider
    except ImportError:
        log.info("No UI provider found — running headless")
        return None


# ---------------------------------------------------------------------------
# Connect sequence — shared by initial connect, reconnect, and restart
# ---------------------------------------------------------------------------

def _probe_and_wait(h_shutdown=None, wait_for_window=True, wait_for_profile=True):
    """Wait for Dragon window + COM readiness + profile load.

    Returns True if ready, False if shutdown was signaled.
    Pushes phase updates to the UI provider.
    """
    from ._ui_dispatch import set_phase
    from ._ui_protocol import (PHASE_WAITING_FOR_DRAGON,
        PHASE_CONNECTING, PHASE_LOADING_PROFILE)

    if wait_for_window:
        set_phase(PHASE_WAITING_FOR_DRAGON)
        if not _wait_for_dragon_window(h_shutdown):
            return False

    set_phase(PHASE_CONNECTING)
    _wait_for_com_ready()

    if wait_for_profile:
        set_phase(PHASE_LOADING_PROFILE)
        _wait_for_profile_via_log(max_wait=30)

    return True


def _connect(natlink):
    """Connect to Dragon via natlink.natConnect(). Returns True on success."""
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_ERROR
    try:
        natlink.natConnect()
        return True
    except Exception as e:
        log.debug("Connect failed: %s", e, exc_info=True)
        set_phase(PHASE_ERROR, str(e))
        return False


def _initial_connect(natlink, discovered, h_shutdown, dragon_was_running):
    """First-time connect: probe, COM connect, activate loaders."""
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_ERROR
    from ._state import _state
    from ._lifecycle import _connect_com, _activate

    if not _probe_and_wait(h_shutdown,
                           wait_for_window=False,
                           wait_for_profile=not dragon_was_running):
        return False

    _state.skip_loader = False
    try:
        _connect_com()
        _activate(discovered)
        return True
    except Exception as e:
        log.error("Connection failed: %s", e)
        set_phase(PHASE_ERROR, str(e))
        return False


# ---------------------------------------------------------------------------
# Restart Dragon (runs on main thread, owns COM objects)
# ---------------------------------------------------------------------------

_restart_lock = threading.Lock()


def _do_restart_on_main(natlink, h_shutdown=None):
    """Restart Dragon from the main thread (COM-safe)."""
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_RESTARTING, PHASE_ERROR
    from natlink_com._dragon import (
        _close_dragon_windows, _is_process_running, _kill_processes,
        start as dragon_start, save_profile,
    )
    from ._state import _state

    if not _restart_lock.acquire(blocking=False):
        log.warning("Restart already in progress — ignoring duplicate")
        return

    try:
        set_phase(PHASE_RESTARTING)
        _state.stop_dragon_monitor()

        conn = _state.conn
        if conn:
            save_profile(conn)

        if _state.connected:
            try:
                natlink.natDisconnect()
            except Exception:
                log.debug("Restart: disconnect error", exc_info=True)

        gc.collect()

        # Graceful close, then force-kill if needed
        _close_dragon_windows()
        if not _wait_for_exit(_is_process_running, timeout=20):
            _kill_processes()
            time.sleep(2)

        dragon_start(wait=30)

        if not _probe_and_wait(h_shutdown, wait_for_window=True, wait_for_profile=True):
            log.info("Restart: shutdown requested while waiting for Dragon")
            return

        if _connect(natlink):
            from ._ui_dispatch import notify_text
            notify_text("[Dragon restarted successfully.]\r\n")
    except Exception:
        log.exception("Restart: unexpected error")
        set_phase(PHASE_ERROR, "Restart failed")
    finally:
        _restart_lock.release()


def _wait_for_exit(is_running_fn, timeout=20):
    """Wait for a process to exit. Returns True if it exited."""
    for i in range(timeout):
        if not is_running_fn():
            log.info("Process exited after %ds", i)
            return True
        time.sleep(1)
    log.warning("Process didn't exit within %ds", timeout)
    return False


# ---------------------------------------------------------------------------
# Disconnect handler
# ---------------------------------------------------------------------------

def _handle_dragon_exited(natlink):
    """Handle Dragon shutdown: disconnect COM, wait for process exit."""
    from ._state import _state

    if _state.connected:
        try:
            _state.set_keep_monitor(True)
            natlink.natDisconnect()
        except Exception:
            log.debug("Disconnect error", exc_info=True)
        finally:
            _state.set_keep_monitor(False)
    gc.collect()

    from natlink_com._dragon import _is_process_running
    from natlink_com._win32 import is_dragon_running
    if _is_process_running():
        log.debug("Waiting for natspeak.exe to exit...")
        for _i in range(10):
            time.sleep(1)
            if not _is_process_running():
                break
            if is_dragon_running():
                log.info("Dragon is restarting...")
                break
        else:
            if _is_process_running():
                log.warning("natspeak.exe still running 10s after disconnect — "
                            "possible unreleased COM objects")


# ---------------------------------------------------------------------------
# Reconnect handler
# ---------------------------------------------------------------------------

def _handle_dragon_reappeared(natlink):
    """Handle Dragon reappearance: probe COM, reconnect."""
    from ._state import _state

    if _state.connected:
        return

    log.info("Dragon detected — reconnecting...")
    if _probe_and_wait(wait_for_window=False, wait_for_profile=True):
        _connect(natlink)


# ---------------------------------------------------------------------------
# Main pump loop
# ---------------------------------------------------------------------------

def _pump_loop(natlink, h_shutdown, h_restart, h_dragon_exited, h_dragon_reappeared):
    """Event dispatch loop. Returns when shutdown is signaled."""
    from natlink_com._pump import pump

    _SHUTDOWN = 0
    _RESTART = 1
    _DRAGON_EXITED = 2
    _DRAGON_REAPPEARED = 3

    try:
        while True:
            rc = pump(h_events=[h_shutdown, h_restart,
                                h_dragon_exited, h_dragon_reappeared],
                      timeout_ms=2000)

            if rc == _SHUTDOWN:
                log.info("Shutdown event signaled")
                break
            elif rc == _RESTART:
                log.info("Restart Dragon event signaled")
                _do_restart_on_main(natlink, h_shutdown)
            elif rc == _DRAGON_EXITED:
                kernel32.ResetEvent(h_dragon_exited)
                log.info("Dragon is shutting down — disconnecting")
                _handle_dragon_exited(natlink)
            elif rc == _DRAGON_REAPPEARED:
                kernel32.ResetEvent(h_dragon_reappeared)
                _handle_dragon_reappeared(natlink)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

def _teardown(natlink, h_shutdown, h_restart, close_monitor_events):
    """Clean disconnect, stop UI, close handles."""
    from ._state import _state
    from ._actions import stop_provider

    if _state.connected:
        natlink.natDisconnect()
    provider = _state.ui_provider
    _state.ui_provider = None
    if provider is not None:
        try:
            stop_provider(provider)
        except Exception:
            pass
    kernel32.CloseHandle(h_shutdown)
    kernel32.CloseHandle(h_restart)
    close_monitor_events()


# ---------------------------------------------------------------------------
# Main entry point — composes the steps above
# ---------------------------------------------------------------------------

def run():
    """Main launcher entry point.

    Acquires single-instance mutex, waits for Dragon, connects,
    and enters the event loop. Each phase is a separate function
    for pluggable orchestration.
    """
    # --- Init ---
    _acquire_single_instance()
    sys.coinit_flags = 2  # STA

    src_dir = str(Path(__file__).resolve().parent.parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    from natlink_com._config import load_config
    cfg = load_config()

    ole32.CoInitializeEx(None, 2)  # STA, idempotent

    from ._logging_setup import init_file_logging
    init_file_logging()

    import natlink_compat as natlink
    from ._state import _state
    from ._lifecycle import discover_loaders as _discover
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_WAITING_FOR_DRAGON

    # --- Discover loaders (they may set custom UI providers) ---
    _state.skip_loader = True
    discovered = _discover()

    if _state.ui_provider is None:
        _state.ui_provider = _discover_ui_provider()

    # --- Create event handles ---
    h_shutdown = kernel32.CreateEventW(None, True, False, _SHUTDOWN_EVENT_NAME)
    h_restart = kernel32.CreateEventW(None, False, False, _RESTART_EVENT_NAME)

    from ._monitor import create_events, close_events
    h_dragon_exited, h_dragon_reappeared = create_events()

    # --- Wait for Dragon ---
    set_phase(PHASE_WAITING_FOR_DRAGON)

    from natlink_com._win32 import is_dragon_running
    if cfg.getboolean("settings", "auto_launch_dragon", fallback=False):
        if not is_dragon_running():
            log.info("Auto-launching Dragon...")
            from natlink_com._dragon import launch
            launch()

    dragon_was_running = is_dragon_running()

    log.info("Waiting for Dragon...")
    if not _wait_for_dragon_window(h_shutdown, h_restart):
        log.info("Shutdown requested while waiting for Dragon")
        kernel32.CloseHandle(h_shutdown)
        kernel32.CloseHandle(h_restart)
        close_events()
        return

    # --- Connect ---
    _initial_connect(natlink, discovered, h_shutdown, dragon_was_running)

    if not _state.is_monitor_alive():
        from ._lifecycle import _start_dragon_monitor
        _start_dragon_monitor()

    # --- Pump ---
    _pump_loop(natlink, h_shutdown, h_restart, h_dragon_exited, h_dragon_reappeared)

    # --- Teardown ---
    _teardown(natlink, h_shutdown, h_restart, close_events)
