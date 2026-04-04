"""UI dispatch — builds state snapshots and notifies UIProviders."""

import logging
import threading

from ._state import _state
from ._ui_protocol import (NatlinkState, PHASE_CONNECTED)

log = logging.getLogger("natlink.compat.ui_dispatch")

_guard = threading.local()


def build_state_snapshot() -> NatlinkState:
    """Build an immutable snapshot of the current natlink state.

    Uses cached values from _state instead of making COM calls,
    avoiding potential deadlocks during deferred callback processing.
    """
    with _state.lock:
        phase = _state.phase
        error_msg = _state.error_message
        backend = _state.backend
        connected = backend is not None and phase == PHASE_CONNECTED
        mic = _state.last_mic_state
        user = _state.last_user_name
        user_dir = _state.last_user_dir
        loader_list = list(_state.loaders)

    version = (0, 0, 0)
    if backend is not None:
        try:
            version = backend.dragon_version
        except Exception:
            pass

    try:
        loaders = tuple(
            getattr(mod, "__name__", str(mod))
            for mod in loader_list
        )
    except Exception:
        loaders = ()

    return NatlinkState(
        connected=connected,
        phase=phase,
        mic_state=mic,
        user_name=user,
        user_directory=user_dir,
        dragon_version=version,
        loaders=loaders,
        error_message=error_msg,
    )


def set_phase(phase: str, error: str = ""):
    """Set the current phase and notify the active UI provider."""
    with _state.lock:
        _state.phase = phase
        _state.error_message = error
    notify_ui()


def notify_ui():
    """Build a state snapshot and push it to the active UI provider."""
    provider = _state.ui_provider
    if provider is None:
        return
    snapshot = build_state_snapshot()
    try:
        provider.on_state_changed(snapshot)
    except Exception:
        log.debug("UIProvider.on_state_changed failed", exc_info=True)


def notify_text(text: str, level: int = logging.INFO):
    """Push text to the active UI provider.

    Level uses standard Python logging values (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR).

    Includes a re-entrancy guard so that provider code that emits output
    (e.g. logging inside on_text) does not cause infinite recursion.
    """
    if getattr(_guard, "active", False):
        return
    provider = _state.ui_provider
    if provider is None:
        return
    _guard.active = True
    try:
        try:
            provider.on_text(text, level)
        except Exception:
            log.debug("UIProvider.on_text failed", exc_info=True)
    except Exception:
        pass
    finally:
        _guard.active = False
