"""_state.py - Global singleton holding natlink session state.

All mutable state lives here so that __init__.py functions and
wrapper objects share a single source of truth.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from natlink_com import NatlinkCOM

log = logging.getLogger("natlink.compat")

# Inline to avoid circular import with _ui_protocol
_PHASE_IDLE = "idle"


class _NatlinkState:
    """Singleton that holds the COM backend and all registries."""

    def __init__(self):
        self.backend: Optional[NatlinkCOM] = None

        # Active loaders (multiple allowed; managed by _loaders.py)
        self.loader_registry: List = []  # List[_LoaderEntry]

        # Active UI provider (default tray/window shell or a replacement)
        self.ui_provider: Optional[object] = None
        self._current_phase: str = _PHASE_IDLE
        self._error_message: str = ""

        # Cached state for UI snapshots (avoids COM calls during callbacks)
        self._last_mic_state: str = ""
        self._last_user_name: str = ""
        self._last_user_dir: str = ""
        self._last_loader_states: tuple = ()  # (name, enabled, running) tuples

        # Global callback stacks — multiple loaders can each register one.
        self.begin_callbacks: List[Callable] = []
        self.change_callbacks: List[Callable] = []
        self.timer_callbacks: List[Callable] = []
        # Handle -> wrapper registries (populated by GramObj.load / DictObj)
        self.grammar_registry: Dict[int, object] = {}  # handle -> GramObj
        self.dict_registry: Dict[int, object] = {}     # handle -> DictObj

        # Callback depth tracking (for getCallbackDepth() API)
        self.callback_depth = 0

        self.during_init: bool = False
        self.during_paused: bool = False
        self._pending_speaker = None      # (user, directory) or None
        self._pending_micstate = None     # mic_state string or None

        # Slow callback warning threshold (ms, 0=disabled)
        self.slow_callback_ms: int = 500

        # Win32 manual-reset event: signaled when natDisconnect starts so
        # waitForSpeech (legacy path) can wake via MsgWaitForMultipleObjects
        # instead of polling.
        from natlink_com._win32 import kernel32
        self._disconnect_event_handle: int = kernel32.CreateEventW(None, True, False, None)

        # Connection mutex handle (Win32)
        self._conn_mutex = None

        self.lock = threading.Lock()

    @property
    def connected(self) -> bool:
        """Derived from backend — no separate flag to get out of sync."""
        return self.backend is not None

    @property
    def conn(self):
        """Current COM connection, or None. Thread-safe."""
        with self.lock:
            backend = self.backend
        return backend.conn if backend and backend.conn else None

    # --- Phase / cached state ---

    @property
    def phase(self) -> str:
        return self._current_phase

    @phase.setter
    def phase(self, value: str):
        self._current_phase = value

    @property
    def error_message(self) -> str:
        return self._error_message

    @error_message.setter
    def error_message(self, value: str):
        self._error_message = value

    @property
    def last_mic_state(self) -> str:
        return self._last_mic_state

    @last_mic_state.setter
    def last_mic_state(self, value: str):
        self._last_mic_state = value

    @property
    def last_user_name(self) -> str:
        return self._last_user_name

    @last_user_name.setter
    def last_user_name(self, value: str):
        self._last_user_name = value

    @property
    def last_user_dir(self) -> str:
        return self._last_user_dir

    @last_user_dir.setter
    def last_user_dir(self, value: str):
        self._last_user_dir = value

    @property
    def last_loader_states(self) -> tuple:
        return self._last_loader_states

    @last_loader_states.setter
    def last_loader_states(self, value: tuple):
        self._last_loader_states = value

    def cache_user_state(self, mic: str, user: str, user_dir: str):
        """Cache mic/user state for UI snapshots."""
        self._last_mic_state = mic
        self._last_user_name = user
        self._last_user_dir = user_dir

    def reset(self):
        """Clear all state (called on natDisconnect)."""
        log.info("Connection state: disconnected (reset)")
        self.backend = None
        self.begin_callbacks.clear()
        self.change_callbacks.clear()
        self.timer_callbacks.clear()
        self.grammar_registry.clear()
        self.dict_registry.clear()
        self.callback_depth = 0
        self.during_init = False
        self.during_paused = False
        self._pending_speaker = None
        self._pending_micstate = None
        self.slow_callback_ms = 500
        from natlink_com._win32 import kernel32
        kernel32.ResetEvent(self._disconnect_event_handle)
        self._current_phase = _PHASE_IDLE
        self._error_message = ""
        self._last_mic_state = ""
        self._last_user_name = ""
        self._last_user_dir = ""
        self._last_loader_states = ()
        if self._conn_mutex:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self._conn_mutex)
            self._conn_mutex = None


# Module-level singleton
_state = _NatlinkState()
