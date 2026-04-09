"""Actions that UIs and the CLI can trigger.

These are plain functions — UIs call them via ``import natlink_compat``.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("natlink.compat")

_loader_states_cache = None
_loader_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Dragon process control
# ---------------------------------------------------------------------------

def is_dragon_running() -> bool:
    """Check if the Dragon NaturallySpeaking process is currently running."""
    from natlink_com._win32 import is_dragon_running as _is_running
    return _is_running()


def start_dragon(wait: int = 20) -> int:
    """Launch Dragon NaturallySpeaking and wait for it to be ready.

    Args:
        wait: Maximum seconds to wait for Dragon to start (default 20).

    Returns:
        0 on success, non-zero on failure.
    """
    from natlink_com._dragon import start
    return start(wait=wait)


def stop_dragon(force: bool = False) -> int:
    """Shut down Dragon NaturallySpeaking.

    Args:
        force: If True, forcefully terminate the process.

    Returns:
        0 on success, non-zero on failure.
    """
    from ._state import _state
    from natlink_com._dragon import stop
    return stop(force=force, conn=_state.conn)


def restart_dragon() -> int:
    """Restart via launcher (COM-safe), or direct fallback."""
    from natlink_com._launcher import signal_restart
    if not signal_restart():
        log.warning("restart_dragon: no launcher running, doing direct restart")
        from natlink_com._dragon import restart
        return restart()
    return 0


def dragon_status() -> int:
    from natlink_com._dragon import status
    return status()


# ---------------------------------------------------------------------------
# Loader lifecycle
# ---------------------------------------------------------------------------

def reload_grammars() -> None:
    """Reload all enabled grammar loaders.

    Deferred to the main (STA) thread — grammar unload/load are COM calls.
    """
    from natlink_com._hidden_wnd import push_to_com
    push_to_com(_reload_grammars_impl)


def _reload_grammars_impl() -> None:
    from ._loaders import reload_loader, get_loaders, _loader_base_name
    from ._loaders import get_disabled_loaders as _get_disabled_loaders
    disabled = _get_disabled_loaders()
    active = [l for l in get_loaders()
              if _loader_base_name(l) not in disabled]
    if active:
        reload_loader(active)


def toggle_loader(name: str) -> None:
    """Toggle a loader between enabled and disabled.

    INI updates happen immediately; loader start/stop is deferred to the
    main (STA) thread because COM calls must not cross thread boundaries.
    """
    global _loader_states_cache
    from ._loaders import get_disabled_loaders as _get_disabled_loaders
    from natlink_com._hidden_wnd import push_to_com
    is_disabled = name in _get_disabled_loaders()
    if is_disabled:
        from natlink_com._config import enable_loader
        enable_loader(name)
        push_to_com(_start_loader_by_name, name)
    else:
        from natlink_com._config import disable_loader
        disable_loader(name)
        push_to_com(_stop_loader_by_name, name)
    invalidate_loader_cache()


def _start_loader_by_name(name):
    from ._loaders import get_all_loader_names, start_and_register
    import importlib
    for loader_name, mod_path in get_all_loader_names():
        if loader_name == name:
            try:
                mod = importlib.import_module(mod_path)
                start_and_register(mod, mod_path)
            except Exception:
                log.exception("Failed to start loader: %s", name)
            break


def _stop_loader_by_name(name):
    from ._loaders import get_loaders, remove_loader, _loader_base_name
    for loader in get_loaders():
        if name == _loader_base_name(loader):
            remove_loader(loader)
            break


def get_loader_states():
    """Return list of (name, enabled) tuples for all discovered loaders."""
    global _loader_states_cache
    with _loader_cache_lock:
        if _loader_states_cache is not None:
            return _loader_states_cache
        try:
            from ._loaders import get_all_loader_names, get_disabled_loaders
            disabled = get_disabled_loaders()
            result = [(name, name not in disabled)
                      for name, _ in get_all_loader_names()]
            _loader_states_cache = result
            return result
        except Exception:
            return []


def invalidate_loader_cache():
    global _loader_states_cache
    with _loader_cache_lock:
        _loader_states_cache = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def toggle_auto_launch() -> None:
    """Toggle whether natlink automatically launches Dragon on connect."""
    from natlink_com._config import toggle_bool_setting
    toggle_bool_setting("settings", "auto_launch_dragon", fallback=False)


def is_auto_launch_enabled() -> bool:
    """Return whether auto-launch of Dragon on connect is enabled."""
    from natlink_com._config import get_bool_setting
    return get_bool_setting("settings", "auto_launch_dragon", fallback=False)


def set_log_level(level: int) -> None:
    """Set natlink's log level (runtime + INI)."""
    from ._logging_setup import _log_root, _notify_handler
    _log_root.setLevel(level)
    if _notify_handler is not None:
        _notify_handler.setLevel(level)
    from natlink_com._config import load_config, save_config
    cfg = load_config()
    if not cfg.has_section("Logging"):
        cfg.add_section("Logging")
    cfg.set("Logging", "ClientLevel", logging.getLevelName(level))
    save_config(cfg)


def get_log_level() -> int:
    """Get current natlink log level (from INI, falling back to runtime)."""
    from natlink_com._config import load_config
    cfg = load_config()
    try:
        raw = cfg.get("Logging", "ClientLevel", fallback="")
        if raw.strip():
            from ._logging_setup import _parse_level, _W
            return _parse_level(raw, _W)
    except Exception:
        pass
    from ._logging_setup import _log_root
    return _log_root.level


# ---------------------------------------------------------------------------
# Mic / shutdown
# ---------------------------------------------------------------------------

def set_mic(state: str) -> None:
    """Set the microphone state.

    Deferred to the COM thread — set_mic_state is a COM call.

    Args:
        state: One of ``'on'``, ``'off'``, or ``'sleeping'``.
    """
    from natlink_com._hidden_wnd import push_to_com
    push_to_com(_set_mic_impl, state)


def _set_mic_impl(state: str) -> None:
    from ._state import _state
    if _state.backend:
        _state.backend.set_mic_state(state)


def exit_natlink() -> None:
    """Shut down natlink cleanly."""
    from natlink_com._launcher import request_shutdown
    request_shutdown()


# ---------------------------------------------------------------------------
# Provider lifecycle helpers (used by the orchestrator / provider registry)
# ---------------------------------------------------------------------------

def stop_provider(provider: object) -> None:
    """Stop a UIProvider."""
    provider.stop()
