"""Launcher orchestration — phase-structured lifecycle.

Phases (each is a named function, called in order by ``run()``):

  1. ``_init_process``        Win32 init: mutex, STA, sys.path, config, file log
  2. ``_discover_subsystems`` Import loaders, resolve UI provider
  3. ``_create_events``       Allocate Win32 event handles for the pump
  4. ``_wait_and_connect``    Auto-launch, wait for Dragon, probe, connect, monitor
  5. ``_pump_loop``           Dispatch shutdown / restart / dragon-exit / reappear
  6. ``_teardown``            Disconnect, stop UI provider, close handles

``run()`` is a pure composition of these phases. Each phase is independently
callable for pluggable orchestration.

Dependency direction: ``natlink_compat`` → ``natlink_com`` (never reversed).

Restart and reconnect are handled by pump events and reuse the same
``_probe_and_wait`` + ``_connect`` helpers that the initial connect uses.
"""

import ctypes
import gc
import logging
import sys
import threading
import time
from dataclasses import dataclass, field
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
# Event handles — bundled so the pump loop and teardown take one parameter
# ---------------------------------------------------------------------------

@dataclass
class LauncherEvents:
    """Win32 event handles owned by the launcher for the lifetime of run()."""
    shutdown: int
    restart: int
    dragon_exited: int
    dragon_reappeared: int

    def close(self):
        for h in (self.shutdown, self.restart,
                  self.dragon_exited, self.dragon_reappeared):
            if h:
                kernel32.CloseHandle(h)


@dataclass
class LauncherSession:
    """Process-scoped launcher session.

    A launcher session may own several COM connection sessions across
    Dragon exits/restarts. The Dragon monitor lives here, not in
    ``natConnect`` or the shared connection state.
    """
    discovered: list
    events: LauncherEvents
    _monitor_thread: threading.Thread | None = None
    _monitor_stop: threading.Event = field(default_factory=threading.Event)

    @property
    def connected(self) -> bool:
        from ._state import _state
        return _state.connected

    @property
    def monitor_stop_event(self) -> threading.Event:
        return self._monitor_stop

    def set_monitor_thread(self, thread) -> None:
        self._monitor_thread = thread
        self._monitor_stop.clear()

    def is_monitor_alive(self) -> bool:
        return self._monitor_thread is not None and self._monitor_thread.is_alive()

    def stop_monitor(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=10)
        self._monitor_thread = None

    # --- Pump dispatch ---
    # _wait_handlers is a list of (handle, callback) pairs. pump_once()
    # calls pump(h_events=[...]) and invokes the matching callback when
    # the corresponding handle fires. Callback returns True to stop the
    # pump, False/None to keep pumping.
    _wait_handlers: list = field(default_factory=list)

    def register_wait(self, handle: int, callback) -> None:
        """Register a (handle, callback) pair for pump_until()."""
        self._wait_handlers.append((handle, callback))

    def pump_until_stopped(self, timeout_ms: int = 2000) -> None:
        """Pump Win32 messages + registered handles until a callback returns True."""
        from natlink_com._pump import pump
        handles = [h for h, _cb in self._wait_handlers]
        while True:
            rc = pump(h_events=handles, timeout_ms=timeout_ms)
            if rc < 0:
                continue  # timeout or transient; keep pumping
            _h, cb = self._wait_handlers[rc]
            if cb() is True:
                return


# ---------------------------------------------------------------------------
# Shared helpers — used by initial connect, reconnect, and restart
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


def _connect(natlink, discovered):
    """Connect to Dragon via ``natlink.natConnect()``. Returns True on success.

    ``discovered`` is the launcher's cached loader list. Threading it
    through every reconnect keeps loader ``setup()`` hooks from re-running
    — they are not idempotent.
    """
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_ERROR
    try:
        natlink.natConnect(discovered_loaders=discovered)
        return True
    except Exception as e:
        log.debug("Connect failed: %s", e, exc_info=True)
        set_phase(PHASE_ERROR, str(e))
        return False


def _start_monitor_if_needed(session):
    """Start the Dragon-process monitor iff it isn't already running.

    The launcher (not natConnect) owns the monitor thread, because the
    events it signals are consumed only by the pump loop.
    """
    if not session.is_monitor_alive():
        from ._monitor import start_dragon_monitor
        start_dragon_monitor(session)


# ---------------------------------------------------------------------------
# Phase 1 — Init process
# ---------------------------------------------------------------------------

def _init_process():
    """Acquire single-instance, set STA, load config, init file logging."""
    _acquire_single_instance()
    sys.coinit_flags = 2  # STA

    src_dir = str(Path(__file__).resolve().parent.parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    ole32.CoInitializeEx(None, 2)  # STA, idempotent

    from ._logging_setup import init_file_logging
    init_file_logging()

    from natlink_com._config import load_config
    return load_config()


# ---------------------------------------------------------------------------
# Phase 2 — Discover subsystems (loaders + UI provider)
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


def _discover_subsystems():
    """Import loaders (so their ``setup()`` hooks can install UI providers),
    then resolve a UI provider if none was installed.

    Returns the discovered loader list; caches it on subsequent reconnects.
    """
    from ._state import _state
    from ._lifecycle import discover_loaders

    discovered = discover_loaders()

    if _state.ui_provider is None:
        _state.ui_provider = _discover_ui_provider()

    return discovered


# ---------------------------------------------------------------------------
# Phase 3 — Create event handles
# ---------------------------------------------------------------------------

def _create_events():
    """Allocate all Win32 event handles used by the pump loop."""
    from ._monitor import DRAGON_EXITED_EVENT, DRAGON_REAPPEARED_EVENT
    h_shutdown = kernel32.CreateEventW(None, True, False, _SHUTDOWN_EVENT_NAME)
    h_restart = kernel32.CreateEventW(None, False, False, _RESTART_EVENT_NAME)
    h_dragon_exited = kernel32.CreateEventW(None, True, False, DRAGON_EXITED_EVENT)
    h_dragon_reappeared = kernel32.CreateEventW(None, True, False, DRAGON_REAPPEARED_EVENT)
    return LauncherEvents(h_shutdown, h_restart, h_dragon_exited, h_dragon_reappeared)


# ---------------------------------------------------------------------------
# Phase 4 — Wait for Dragon, connect, start monitor
# ---------------------------------------------------------------------------

def _wait_and_connect(session, cfg, natlink):
    """Auto-launch Dragon if configured, wait for its window, probe COM,
    connect, and start the process monitor.

    Returns True on successful connection, False if shutdown was requested
    while waiting for Dragon.
    """
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_WAITING_FOR_DRAGON
    from natlink_com._win32 import is_dragon_running

    set_phase(PHASE_WAITING_FOR_DRAGON)

    if cfg.getboolean("settings", "auto_launch_dragon", fallback=False):
        if not is_dragon_running():
            log.info("Auto-launching Dragon...")
            from natlink_com._dragon import launch
            launch()

    dragon_was_running = is_dragon_running()

    log.info("Waiting for Dragon...")
    if not _wait_for_dragon_window(session.events.shutdown, session.events.restart):
        log.info("Shutdown requested while waiting for Dragon")
        return False

    # Window already observed above; only wait for profile load if we
    # had to auto-launch Dragon ourselves.
    if not _probe_and_wait(session.events.shutdown,
                           wait_for_window=False,
                           wait_for_profile=not dragon_was_running):
        return False

    if not _connect(natlink, session.discovered):
        return False
    _start_monitor_if_needed(session)
    return True


# ---------------------------------------------------------------------------
# Pump-event handlers
# ---------------------------------------------------------------------------

_restart_lock = threading.Lock()


def _aborting(session) -> bool:
    """True if shutdown has been signaled on this session."""
    return kernel32.WaitForSingleObject(session.events.shutdown, 0) == 0


def _do_restart_on_main(session, natlink):
    """Restart Dragon from the main thread (COM-safe).

    Restart runs synchronously on the main thread, so it blocks the pump for
    up to ~60s across stop + start + probe. Between stages we poll the
    shutdown event and bail out early; the outer pump observes the same
    event next iteration and _teardown runs. _dragon.stop / _dragon.start
    don't accept a shutdown handle, so we cannot interrupt them mid-call —
    the checks straddle them instead.
    """
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_RESTARTING, PHASE_ERROR
    from natlink_com import _dragon
    from ._state import _state

    if not _restart_lock.acquire(blocking=False):
        log.warning("Restart already in progress — ignoring duplicate")
        return

    try:
        set_phase(PHASE_RESTARTING)
        session.stop_monitor()
        if _aborting(session):
            log.info("Restart: shutdown requested after stop_monitor — aborting")
            return

        # Save profile while COM is still live; then disconnect and stop.
        # _dragon.stop() handles WM_CLOSE → wait → force-kill internally.
        conn = _state.conn
        if conn:
            _dragon.save_profile(conn)

        if _state.connected:
            try:
                natlink.natDisconnect()
            except Exception:
                log.debug("Restart: disconnect error", exc_info=True)

        gc.collect()
        if _aborting(session):
            log.info("Restart: shutdown requested before _dragon.stop — aborting")
            return

        _dragon.stop(force=False)
        if _aborting(session):
            log.info("Restart: shutdown requested after _dragon.stop — aborting")
            return

        _dragon.start(wait=30)
        if _aborting(session):
            # Dragon was re-launched but no client is attached. _teardown
            # won't kill it — matches existing semantics (quitting natlink
            # doesn't imply quitting Dragon).
            log.info("Restart: shutdown requested after _dragon.start — "
                     "aborting (Dragon left running)")
            return

        if not _probe_and_wait(session.events.shutdown,
                               wait_for_window=True,
                               wait_for_profile=True):
            log.info("Restart: shutdown requested while waiting for Dragon")
            return

        if _connect(natlink, session.discovered):
            _start_monitor_if_needed(session)
            from ._ui_dispatch import notify_text
            notify_text("[Dragon restarted successfully.]\r\n")
    except Exception:
        log.exception("Restart: unexpected error")
        set_phase(PHASE_ERROR, "Restart failed")
    finally:
        _restart_lock.release()


def _handle_dragon_exited(session, natlink):
    """Handle Dragon shutdown: disconnect COM. Returns immediately; the
    Dragon monitor will signal _DRAGON_REAPPEARED if Dragon comes back."""
    if session.connected:
        try:
            natlink.natDisconnect()
        except Exception:
            log.debug("Disconnect error", exc_info=True)
    gc.collect()
    _log_unreleased_com_warning_async()


def _log_unreleased_com_warning_async():
    """Background check: warn if natspeak.exe survives 10s after disconnect."""
    def _check():
        from natlink_com._dragon import _is_process_running
        from natlink_com._win32 import is_dragon_running
        for _i in range(10):
            time.sleep(1)
            if not _is_process_running() or is_dragon_running():
                return
        if _is_process_running():
            log.warning("natspeak.exe still running 10s after disconnect — "
                        "possible unreleased COM objects")
    threading.Thread(target=_check, daemon=True,
                     name="dragon-exit-diagnostic").start()


def _handle_dragon_reappeared(session, natlink):
    """Handle Dragon reappearance: probe COM, reconnect, restart monitor."""
    if session.connected:
        return

    log.info("Dragon detected — reconnecting...")
    if _probe_and_wait(wait_for_window=False, wait_for_profile=True):
        if _connect(natlink, session.discovered):
            _start_monitor_if_needed(session)


# ---------------------------------------------------------------------------
# Phase 5 — Pump loop
# ---------------------------------------------------------------------------

_pump_active = threading.local()


def _pump_loop(session, natlink):
    """Event dispatch loop. Returns when shutdown is signaled."""
    def on_shutdown():
        log.info("Shutdown event signaled")
        return True  # stop pumping

    def on_restart():
        log.info("Restart Dragon event signaled")
        _do_restart_on_main(session, natlink)

    def on_dragon_exited():
        kernel32.ResetEvent(session.events.dragon_exited)
        log.info("Dragon is shutting down — disconnecting")
        _handle_dragon_exited(session, natlink)

    def on_dragon_reappeared():
        kernel32.ResetEvent(session.events.dragon_reappeared)
        _handle_dragon_reappeared(session, natlink)

    session.register_wait(session.events.shutdown, on_shutdown)
    session.register_wait(session.events.restart, on_restart)
    session.register_wait(session.events.dragon_exited, on_dragon_exited)
    session.register_wait(session.events.dragon_reappeared, on_dragon_reappeared)

    _pump_active.running = True
    try:
        session.pump_until_stopped(timeout_ms=2000)
    except KeyboardInterrupt:
        pass
    finally:
        _pump_active.running = False


def is_pump_active_on_this_thread() -> bool:
    """True if the launcher's pump is currently running on the calling thread."""
    return getattr(_pump_active, "running", False)


# ---------------------------------------------------------------------------
# Phase 6 — Teardown
# ---------------------------------------------------------------------------

def _teardown(session, natlink):
    """Clean disconnect, stop UI provider, close event handles."""
    from ._state import _state
    from ._actions import stop_provider

    session.stop_monitor()

    if _state.connected:
        natlink.natDisconnect()

    provider = _state.ui_provider
    _state.ui_provider = None
    if provider is not None:
        try:
            stop_provider(provider)
        except Exception:
            pass

    session.events.close()


# ---------------------------------------------------------------------------
# Entry point — pure composition of the phases above
# ---------------------------------------------------------------------------

def run():
    """Main launcher entry point."""
    cfg = _init_process()
    discovered = _discover_subsystems()
    session = LauncherSession(discovered=discovered, events=_create_events())

    import natlink_compat as natlink
    try:
        if _wait_and_connect(session, cfg, natlink):
            _pump_loop(session, natlink)
    finally:
        _teardown(session, natlink)
