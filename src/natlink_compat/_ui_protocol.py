"""UI protocol for natlink.

Third parties implement UIProvider to own natlink's UI surface.
Natlink pushes state changes and text output; the provider decides
how to display them.  To issue commands back, ``import natlink_compat``
and call its module-level functions (e.g. ``natlink_compat.restart_dragon()``).

UIProvider contract::

    def on_state_changed(self, state: NatlinkState) -> None: ...
    def on_text(self, text: str, level: int = 20) -> None: ...
    def stop(self) -> None: ...

Exactly one provider is active at a time. Third parties replace the
default provider by registering their own implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable, Tuple

# Well-known phases (not an enum — extensible by third parties)
PHASE_IDLE = "idle"
PHASE_WAITING_FOR_DRAGON = "waiting_for_dragon"
PHASE_CONNECTING = "connecting"
PHASE_LOADING_PROFILE = "loading_profile"
PHASE_CONNECTED = "connected"
PHASE_RESTARTING = "restarting"
PHASE_ERROR = "error"


@dataclass(frozen=True)
class NatlinkState:
    """Immutable snapshot of natlink's current state.

    Passed to UIProvider.on_state_changed() whenever state changes.
    Frozen to avoid race conditions — the provider gets a copy,
    not a reference to mutable state.

    Serializable via ``dataclasses.asdict(state)`` for cross-process
    bridges (named pipe, websocket, etc.).
    """
    connected: bool = False
    phase: str = PHASE_IDLE
    mic_state: str = ""         # "on", "off", "sleeping", ""
    user_name: str = ""
    user_directory: str = ""
    dragon_version: Tuple[int, int, int] = (0, 0, 0)
    loader_states: Tuple[Tuple[str, bool, bool], ...] = ()  # (name, enabled, running)
    error_message: str = ""


@runtime_checkable
class UIProvider(Protocol):
    """Protocol for natlink UI providers.

    Implement this to provide a custom tray icon, output window,
    IPC bridge, or any other UI. Natlink calls on_state_changed when
    connection state, mic state, or user changes. Natlink calls on_text
    when text output is produced.

    To issue commands, import natlink_compat and call functions directly.

    Threading: all methods may be called from any thread.
    Implementations must be thread-safe.
    """

    def on_state_changed(self, state: NatlinkState) -> None:
        """Called when any natlink state changes."""
        ...

    def on_text(self, text: str, level: int = 20) -> None:
        """Called when text output is produced.

        Level uses standard Python logging values:
        10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR.

        Called synchronously on the caller's thread — typically the
        STA main thread that pumps Dragon COM callbacks. Blocking here
        stalls the pump and can wedge recognition. Queue any blocking
        I/O or slow work to the provider's own thread and return
        promptly.
        """
        ...

    def stop(self) -> None:
        """Clean up resources on shutdown."""
        ...
