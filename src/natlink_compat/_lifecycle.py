"""_lifecycle.py - Connection lifecycle: natConnect, natDisconnect, waitForSpeech.

Natlink is a "global client" — not tied to a specific application window.
"This implementation is designed to be a global client and not a app-specific
client.  That decision simplifies the design somewhat."
— Joel Gould, appsupp.cpp

As a global client, Dragon calls Register once at startup and UnRegister once
at shutdown.  AddProcess/EndProcess (per-app lifecycle) are no-ops.
"""

import logging
import threading
import time

from natlink_com import NatlinkCOM

from ._state import _state
from ._helpers import _require_not_during_init, _require_not_paused


def _atexit_disconnect():
    """Emergency cleanup on process exit — unregister sinks + Resume."""
    if _state.connected:
        try:
            natDisconnect()
        except Exception:
            pass
from . import _callbacks


log = logging.getLogger("natlink.compat")


def _teardown_objects():
    """Unload all grammars and destroy all dictation objects."""
    for label, registry, method in [
        ("grammars", _state.grammar_registry, "unload"),
        ("dictation objects", _state.dict_registry, "_destroy"),
    ]:
        with _state.lock:
            objects = list(registry.values())
        if objects:
            log.debug("natDisconnect: tearing down %d %s", len(objects), label)
        for obj in objects:
            try:
                getattr(obj, method)()
            except Exception:
                log.debug("%s teardown failed", label, exc_info=True)


def _start_dragon_monitor():
    from ._monitor import start_dragon_monitor
    start_dragon_monitor(_state)


class _NatConnectContextManager:
    """Context manager returned by natConnect for optional with-statement use."""
    def __enter__(self):
        return self
    def __exit__(self, *args):
        natDisconnect()
        return False


def discover_loaders():
    """Phase 1: Import loader modules so they can register providers/helpers.

    Returns list of (module, module_name) tuples. Does NOT start loaders.
    """
    from ._loaders import discover_and_import
    discovered = discover_and_import()

    # Call optional setup() hook on each discovered loader
    for mod, name in discovered:
        setup_fn = getattr(mod, "setup", None)
        if setup_fn and callable(setup_fn):
            try:
                setup_fn()
            except Exception:
                log.debug("Loader setup() failed: %s", name, exc_info=True)

    return discovered


def _read_runtime_pid():
    """Read the stale PID from natlink.ini [runtime]. Returns int or None."""
    import os
    try:
        from natlink_com._config import load_config
        pid = load_config().getint("runtime", "pid", fallback=0)
        return pid if pid and pid != os.getpid() else None
    except Exception:
        return None


def _write_runtime_pid():
    """Write our PID to natlink.ini [runtime]."""
    import os
    try:
        from natlink_com._config import load_config, save_config
        cfg = load_config()
        if not cfg.has_section("runtime"):
            cfg.add_section("runtime")
        cfg.set("runtime", "pid", str(os.getpid()))
        save_config(cfg)
    except Exception:
        pass


def _clear_runtime_pid():
    """Remove our PID from natlink.ini [runtime]."""
    try:
        from natlink_com._config import load_config, save_config
        cfg = load_config()
        if cfg.has_section("runtime"):
            cfg.remove_option("runtime", "pid")
            save_config(cfg)
    except Exception:
        pass


def _connect_com():
    """Pure COM connection. No UI, no loaders.

    The backend's connect() method implements CDragonCode::initGetSiteObject:
    "We connect to NatSpeak through a site object which is a better way
    than using the SAPI enumerator objects because it also gives us access
    to the other DgnSAPI interfaces at the same time."
    — Joel Gould, DragonCode.cpp (initGetSiteObject)
    """
    import ctypes
    from ._win32 import kernel32
    _NATLINK_CONN_MUTEX = "NatlinkConnectionActive"
    _state._conn_mutex = kernel32.CreateMutexW(None, True, _NATLINK_CONN_MUTEX)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        stale_pid = _read_runtime_pid()
        if stale_pid:
            log.warning(
                "Another natlink process is already connected to Dragon "
                "(PID %d). Kill it for a clean connection.", stale_pid)
        else:
            log.warning(
                "Another natlink process is already connected to Dragon. "
                "Cross-process grammar routing may cause unexpected behavior.")

    _write_runtime_pid()

    _state.during_init = True
    try:
        backend = NatlinkCOM()
        backend.connect()
        _state.backend = backend
        _callbacks.register_all()
    finally:
        _state.during_init = False


def _activate(discovered_loaders=None):
    """Phase 3: diagnostics, state publication, and loader startup."""
    from ._logging_setup import _setup_logging_and_redirect
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_CONNECTED

    try:
        import sys as _sys
        backend = _state.backend
        backend.display_text(f"Python Version: {_sys.version}\r\n", False)
        if discovered_loaders:
            for mod, mod_name in discovered_loaders:
                base = mod_name.split(".")[0]
                ver = getattr(mod, "__version__", None)
                if ver is None:
                    pkg = _sys.modules.get(base)
                    if pkg is not None:
                        ver = getattr(pkg, "__version__", None)
                if ver:
                    backend.display_text(f"{base} Version: {ver}\r\n", False)
        backend.display_text("Natlink is loaded...\r\n\r\n", False)
        if not _state.skip_loader and not discovered_loaders:
            from ._loaders import get_all_loader_names, get_disabled_loaders
            all_names = get_all_loader_names()
            if all_names:
                disabled = get_disabled_loaders()
                backend.display_text(
                    "WARNING: All discovered loaders are disabled.\r\n", True)
                for name, mod_path in all_names:
                    status = "disabled" if name in disabled else "enabled"
                    backend.display_text(
                        f"  {name} ({mod_path}) [{status}]\r\n", True)
            else:
                backend.display_text(
                    "WARNING: No loaders discovered.\r\n"
                    "Install a loader package or check your configuration.\r\n", True)
    except Exception:
        log.debug("Failed to display startup text", exc_info=True)

    _setup_logging_and_redirect()

    if not getattr(_atexit_disconnect, "_registered", False):
        import atexit
        atexit.register(_atexit_disconnect)
        _atexit_disconnect._registered = True

    log.info("Connection state: connected")

    # Cache initial state for UI snapshots (avoids COM calls during callbacks)
    try:
        mic = _state.backend.get_mic_state()
    except Exception:
        mic = ""
    try:
        user, user_dir = _state.backend.get_current_user()
    except Exception:
        user, user_dir = "", ""
    _state.cache_user_state(mic, user, user_dir)

    set_phase(PHASE_CONNECTED)

    if not _state.is_monitor_alive():
        _start_dragon_monitor()

    if not _state.skip_loader and discovered_loaders:
        from ._loaders import start_and_register
        for mod, mod_name in discovered_loaders:
            start_and_register(mod, mod_name)


def natConnect(bUseThreads: bool = False) -> _NatConnectContextManager:
    """Connect to Dragon NaturallySpeaking.

    This will launch Dragon if it is not already running. As a side effect,
    natlink acquires COM interface pointers into Dragon's speech engine.

    Returns a context manager that calls natDisconnect on exit::

        with natlink.natConnect():
            # connected to Dragon
            ...
        # automatically disconnected

    Args:
        bUseThreads: Accepted for backwards compatibility (threading is
            always enabled in the current implementation).
    """
    if _state.connected:
        log.debug("natConnect: already connected, disconnecting first")
        natDisconnect()

    _state._disconnect_event.clear()
    log.info("natConnect: connecting to Dragon via COM...")

    # Phase 1: Discovery — import loaders
    discovered = []
    if not _state.skip_loader:
        discovered = discover_loaders()
        for _mod, mod_name in discovered:
            log.info("Loader: %s", mod_name)

    # Phase 2: Connection — pure COM
    _connect_com()
    log.info("Connected to Dragon.")

    # Phase 3: Activation — diagnostics, start loaders
    _activate(discovered)

    return _NatConnectContextManager()


def natDisconnect() -> None:
    """Disconnect from Dragon by releasing all internal COM interface pointers.

    This will cause Dragon to stop running if it was launched by natConnect.
    All grammars, result objects, and dictation objects are invalidated.
    """
    from ._ui_dispatch import set_phase
    from ._ui_protocol import PHASE_IDLE

    log.info("natDisconnect: cleaning up...")

    # Update tray immediately — COM teardown may block if Dragon is gone
    set_phase(PHASE_IDLE)

    # Only stop the monitor on explicit disconnect (natlink stop / uninstall).
    # When the launcher disconnects due to Dragon exit, the monitor must
    # stay alive to detect Dragon reappearing.
    if not _state.should_keep_monitor():
        _state.stop_dragon_monitor()

    # Disable COM timer before stopping loaders (needs live backend)
    if _state.timer_callbacks:
        try:
            _state.backend.set_timer_callback(False)
        except Exception:
            pass

    from ._loaders import stop_loaders
    stop_loaders()

    _state._disconnect_event.set()  # unblock waitForSpeech

    # Match original C++ CDragonCode::natDisconnect order:
    # 0. "check for special training mode which we should cancel"
    #    — Joel Gould, DragonCode.cpp (natDisconnect, line 1865)
    #    (not applicable here: training mode is Dragon-internal)
    # 1. Unregister engine sink — "The Unregister call will caused
    #    NatSpeak to release its references on the notification sink"
    #    — Joel Gould, DragonCode.cpp (natDisconnect, line 1875-1877)
    # 2. Unload grammars + destroy results + destroy dicts (releaseObjects)
    # 3. Release COM interfaces
    # Sinks MUST be unregistered first — otherwise Dragon's RPC threads
    # can fire callbacks that acquire _state.lock while the main thread
    # is also trying to acquire it, causing a deadlock.
    if _state.backend is not None:
        try:
            _state.backend.unregister_sinks()
        except Exception:
            log.debug("Sink unregistration failed during disconnect", exc_info=True)

    # Clear callback slots AFTER sinks are unregistered — between
    # unregister_sinks and this point, Dragon may still deliver in-flight
    # callbacks that need the slots to call Resume (preventing freeze).
    _callbacks.unregister_all()

    # Flush logs and restore stdout/stderr before tearing down COM.
    from ._logging_setup import teardown_logging
    teardown_logging()

    _teardown_objects()

    if _state.backend is not None:
        try:
            _state.backend.disconnect()
        except Exception:
            log.debug("Backend disconnect failed", exc_info=True)

    # Release connection mutex and clear PID from INI
    _clear_runtime_pid()
    if hasattr(_state, '_conn_mutex') and _state._conn_mutex:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_state._conn_mutex)
        _state._conn_mutex = None

    _state.reset()
    log.info("natDisconnect: done")


def isNatSpeakRunning() -> int:
    """Check if Dragon NaturallySpeaking is running.

    Returns 1 if Dragon is running, 0 otherwise. This is the only natlink
    function that can be called before natConnect.
    """
    if _state.backend is not None:
        try:
            return 1 if _state.backend.is_dragon_running_remote() else 0
        except Exception:
            return 1  # Connected means running
    try:
        from ._win32 import user32, DRAGON_CLS
        return 1 if user32.FindWindowW(DRAGON_CLS, None) else 0
    except Exception:
        log.debug("isNatSpeakRunning: FindWindowW failed", exc_info=True)
        return 0


def waitForSpeech(timeout_ms: int = 0) -> None:
    """Enter a Windows message loop to allow speech to be processed.

    Previously established callback functions will be invoked as speech
    events occur. The function blocks until natDisconnect is called or the
    timeout elapses.

    Args:
        timeout_ms: Timeout in milliseconds. ``0`` means wait indefinitely.
            A negative value suppresses any UI and returns when the timeout
            elapses.
    """
    _require_not_during_init("waitForSpeech")
    _require_not_paused("waitForSpeech")
    if not _state.connected:
        return
    log.info("waitForSpeech: pumping messages until disconnect...")
    from ._win32 import kernel32
    from natlink_com._pump import pump

    _POLL_MS = 500
    deadline = (time.monotonic() + timeout_ms / 1000.0) if timeout_ms > 0 else None
    h_tmp = kernel32.CreateEventW(None, True, False, None)
    try:
        while not _state._disconnect_event.is_set():
            if deadline:
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining <= 0:
                    break
                wait_ms = min(remaining, _POLL_MS)
            else:
                wait_ms = _POLL_MS
            pump(h_event=h_tmp, timeout_ms=wait_ms, label="")
    finally:
        kernel32.CloseHandle(h_tmp)
    log.info("waitForSpeech: unblocked")
