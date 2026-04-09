"""_loaders.py - Loader discovery, lifecycle, and runtime management.

Consolidates all loader concerns: discovery (entry points + natlinkcore
fallback), start/stop/reload, and the public add/remove/get API.

Multiple loaders can be active simultaneously (e.g. natlinkcore + dragonfly).
"""

import importlib
import logging
import sys as _sys
import traceback

from ._logging_setup import _NotifyTextHandler
from ._state import _state

log = logging.getLogger("natlink.compat")

_loader_module_names = {}


def _display(text, level=20):
    """Write to the message window if available."""
    try:
        from ._ui_dispatch import notify_text
        notify_text(text, level)
    except Exception:
        log.debug("_display failed", exc_info=True)


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

def _loader_name(loader):
    """Best-effort human-readable name for a loader."""
    return getattr(loader, "__name__", None) or type(loader).__name__


def _loader_base_name(loader):
    """Top-level package name (e.g. 'natlinkcore' from 'natlinkcore.loader')."""
    return _get_module_name(loader).split(".")[0]


def _get_module_name(loader):
    """Return the module name string for a loader, or '' if unknown."""
    with _state.lock:
        return _loader_module_names.get(loader, "")


def _as_list(loader_or_loaders):
    """Normalize a single loader or list to a list."""
    if isinstance(loader_or_loaders, (list, tuple)):
        return list(loader_or_loaders)
    return [loader_or_loaders]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def get_disabled_loaders():
    """Read [loaders] section from natlink.ini to find disabled loaders.

    Returns a set of loader names marked 'disabled'.
    """
    try:
        from natlink_com._config import load_config
        cfg = load_config()
        if not cfg.has_section("loaders"):
            return set()
        return {
            name for name, value in cfg.items("loaders")
            if value.strip().lower() == "disabled"
        }
    except Exception:
        log.debug("Could not read [loaders] config", exc_info=True)
        return set()


def get_all_loader_names():
    """Return all discoverable loader names (entry points + natlinkcore fallback).

    Returns list of (name, module_path) tuples. Does not import modules.
    """
    names = []
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group="natlink.loaders"):
            names.append((ep.name, ep.value))
    except Exception:
        pass
    if not any(n == "natlinkcore" for n, _ in names):
        from importlib.util import find_spec
        if find_spec("natlinkcore.loader") is not None:
            names.append(("natlinkcore", "natlinkcore.loader"))
    return names


def discover_and_import():
    """Find and import all enabled loaders.

    Returns list of (module, module_name_str) tuples.
    """
    all_names = get_all_loader_names()
    if not all_names:
        log.warning("No loaders discovered.")
        return []

    disabled = get_disabled_loaders()
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Loader discovery: found %d loader(s)", len(all_names))
        for name, mod_path in all_names:
            status = "disabled" if name in disabled else "enabled"
            log.debug("  %s (%s) [%s]", name, mod_path, status)

    loaders = []
    for name, mod_path in all_names:
        if name in disabled:
            log.info("Loader disabled in config, skipping: %s", name)
            continue
        try:
            mod = importlib.import_module(mod_path)
            loaders.append((mod, mod_path))
            log.info("Discovered loader: %s (%s)", name, mod_path)
        except Exception:
            log.exception("Failed to load loader: %s", name)

    if not loaders:
        log.warning("All discovered loaders are disabled. Check [loaders] in natlink.ini.")

    return loaders


# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------

def _adopt_loader_logger(loader, mod_name):
    """Wire a loader's logger into the messages window.

    Replaces any StreamHandler the loader installed with a
    _NotifyTextHandler so output goes directly to the UI —
    no dependency on stdout redirect.

    Loaders can opt out by setting ``natlink_manage_logging = False``.
    Called after start() so the loader's own setup is complete.
    """
    if not mod_name:
        return
    if getattr(loader, "natlink_manage_logging", True) is False:
        return
    base = mod_name.split(".")[0]
    logger = logging.getLogger(base)
    if any(isinstance(h, _NotifyTextHandler) for h in logger.handlers):
        return
    for h in logger.handlers[:]:
        if type(h) is logging.StreamHandler:
            logger.removeHandler(h)
    nh = _NotifyTextHandler()
    nh.setLevel(logging.INFO)
    nh.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    logger.addHandler(nh)


def start_loader(loader, mod_name=""):
    """Start a single loader. Returns True on success, False on failure."""
    name = _loader_name(loader)
    try:
        start_fn = getattr(loader, "start", None) or getattr(loader, "run", None)
        if start_fn is None:
            raise AttributeError(f"{name} has no start() or run()")
        log.info("Starting loader: %s", name)
        start_fn()
        _adopt_loader_logger(loader, mod_name)
        log.info("Loader started: %s", name)
        return True
    except Exception:
        log.exception("Loader failed to start: %s", name)
        _display(f"Loader failed: {name}\r\n", level=40)
        _display(traceback.format_exc(), level=40)
        return False


def start_and_register(loader, mod_name=""):
    """Start a loader and register it in _state.loaders.

    Handles loaders that self-register during start() (e.g. natlinkcore
    sets natlink.active_loader = self) and loaders that don't.
    Returns True if the loader started successfully.
    """
    with _state.lock:
        count_before = len(_state.loaders)

    ok = start_loader(loader, mod_name=mod_name)
    if not ok:
        return False

    with _state.lock:
        # Detect if loader self-registered during start()
        self_registered = len(_state.loaders) > count_before
        if self_registered:
            registered = _state.loaders[-1]
            if mod_name:
                _loader_module_names[registered] = mod_name
        elif loader not in _state.loaders:
            _state.loaders.append(loader)
            if mod_name:
                _loader_module_names[loader] = mod_name
            log.info("Loader registered (already running): %s", _loader_name(loader))
    return True


def stop_loader(loader):
    """Stop a single loader.

    Tries stop() (LoaderProtocol), falls back to
    unload_all_loaded_modules() (natlinkcore compat).
    Removes any callbacks this loader registered.
    """
    name = _loader_name(loader)
    log.info("Stopping loader: %s", name)
    try:
        if hasattr(loader, "stop"):
            loader.stop()
        elif hasattr(loader, "unload_all_loaded_modules"):
            loader.unload_all_loaded_modules()
    except Exception:
        log.exception("Loader stop failed: %s", name)

    from ._callbacks import _remove_callbacks_for
    _remove_callbacks_for(loader)


def stop_loaders():
    """Stop all active loaders. Called by natDisconnect."""
    for loader in list(_state.loaders):
        stop_loader(loader)
    clear_all()


# ---------------------------------------------------------------------------
# Public API: add / remove / reload / get
# ---------------------------------------------------------------------------

def add_loader(loaders, *, _module_name=""):
    """Add and start one or more loaders.

    Accepts a single loader or a list. Each must have a start() or run()
    method. If connected, start() is called immediately.
    """
    for loader in _as_list(loaders):
        with _state.lock:
            if loader in _state.loaders:
                log.debug("add_loader: %s already active", _loader_name(loader))
                continue
            if not (hasattr(loader, "start") or hasattr(loader, "run")):
                raise TypeError(
                    f"Loader must have start() or run(), got {type(loader)}")
        if _state.connected:
            ok = start_loader(loader)
            if not ok:
                continue
            with _state.lock:
                if loader not in _state.loaders:
                    _state.loaders.append(loader)
        else:
            with _state.lock:
                _state.loaders.append(loader)
        with _state.lock:
            if _module_name:
                _loader_module_names[loader] = _module_name
        log.info("Loader added: %s", _loader_name(loader))


def remove_loader(loaders):
    """Stop and remove one or more loaders. No-op for inactive loaders."""
    for loader in _as_list(loaders):
        with _state.lock:
            if loader not in _state.loaders:
                continue
        stop_loader(loader)
        with _state.lock:
            if loader in _state.loaders:
                _state.loaders.remove(loader)
            _loader_module_names.pop(loader, None)
        log.info("Loader removed: %s", _loader_name(loader))


def reload_loader(loaders=None):
    """Reload grammars for one, several, or all loaders.

    If the loader has trigger_load() (natlinkcore), calls it in-place.
    Otherwise falls back to full stop/reimport/restart.
    """
    if loaders is None:
        targets = [(l, _loader_module_names.get(l))
                    for l in list(_state.loaders)]
    else:
        targets = [(l, _loader_module_names.get(l))
                    for l in _as_list(loaders)]

    if not targets:
        _display("No active loaders to reload.\r\n")
        return

    for target, mod_name in targets:
        trigger = getattr(target, "trigger_load", None)
        if trigger is not None:
            name = _loader_name(target)
            log.info("Reloading grammars: %s", name)
            _display(f"Reloading grammars ({name})...\r\n")
            try:
                trigger(force_load=True)
                _display(f"Grammars reloaded.\r\n")
            except Exception:
                log.exception("trigger_load failed: %s", name)
                _display(f"Reload failed: {name}\r\n", level=40)
            continue

        # Slow path: full stop/reimport/restart
        if target in _state.loaders:
            stop_loader(target)
            with _state.lock:
                if target in _state.loaders:
                    _state.loaders.remove(target)
                _loader_module_names.pop(target, None)

        if mod_name:
            mod = _sys.modules.get(mod_name)
            try:
                if mod is not None:
                    importlib.reload(mod)
                else:
                    mod = importlib.import_module(mod_name)
                start_and_register(mod, mod_name)
            except Exception:
                log.exception("Failed to reload loader: %s", mod_name)
        else:
            log.warning("Cannot reload %s: no module name known",
                        _loader_name(target))


def register_running_loader(loader):
    """Register a loader that is already running (legacy loader support)."""
    with _state.lock:
        if loader in _state.loaders:
            return
        _state.loaders.append(loader)
    log.info("Loader registered (already running): %s", _loader_name(loader))


def get_loaders():
    """Return a list of all active loaders (snapshot)."""
    with _state.lock:
        return list(_state.loaders)


def clear_all():
    """Clear loaders and module name tracking."""
    with _state.lock:
        _state.loaders.clear()
        _loader_module_names.clear()
