"""_speech.py - Speech playback and scripting functions."""

import struct
from typing import List, Tuple

from ._helpers import _require_connected, _require_not_during_init, _require_not_paused, com_call
from ._state import _state
from ._playstring import expand_keys as _expand_playstring_keys


def _coerce_event_triples(events) -> bytes:
    if not isinstance(events, list):
        raise TypeError("the argument to playEvents must be a list of tuples")

    buf = bytearray()
    for ev in events:
        if not isinstance(ev, tuple):
            raise TypeError("the list passed to playEvents must contain tuples")
        try:
            msg = int(ev[0])
            wparam = int(ev[1]) if len(ev) > 1 else 0
            lparam = int(ev[2]) if len(ev) > 2 else 0
        except Exception as exc:
            raise TypeError("the list passed to playEvents must contain tuples") from exc
        buf += struct.pack("<III", msg, wparam, lparam)
    return bytes(buf)


def _coerce_exec_script_args(args):
    if args is None:
        return None
    if not isinstance(args, list):
        raise TypeError("the second argument to execScript must be a list of words")
    if not all(isinstance(word, str) for word in args):
        raise TypeError("the second argument to execScript must be a list of words")
    return args


def _coerce_mimic_words(args) -> List[str]:
    if len(args) == 0:
        raise TypeError("recognitionMimic requires at least 1 argument")

    if len(args) == 1 and isinstance(args[0], (list, tuple)) and len(args[0]):
        words = list(args[0])
    else:
        words = list(args)

    if not words:
        raise TypeError("recognitionMimic requires at least 1 argument")
    if not all(isinstance(word, str) for word in words):
        raise TypeError("all arguments passed to recognitionMimic must be strings")
    return words


def playString(keys: str, flags: int = 0) -> None:
    """Send keystrokes via Dragon (SendKeys-style)."""
    _require_connected()
    _require_not_during_init("playString")
    _require_not_paused("playString")
    keys = _expand_playstring_keys(keys)
    com_call("playString", _state.backend.play_string, keys, flags)


def playEvents(events: List[Tuple[int, ...]]) -> None:
    """Play keyboard/mouse events.

    Each event is a tuple of 1-3 ints: (msg, wParam=0, lParam=0).
    """
    _require_connected()
    _require_not_during_init("playEvents")
    _require_not_paused("playEvents")
    com_call("playEvents", _state.backend.play_events, _coerce_event_triples(events))


def execScript(command: str, args: List[str] = None,
               comment: str = "") -> None:
    """Execute a Dragon scripting command.

    If args is provided, Dragon substitutes %1, %2, ... in the script
    at execution time via ExecuteScriptWithListResults.
    """
    _require_connected()
    _require_not_during_init("execScript")
    _require_not_paused("execScript")
    com_call("execScript", _state.backend.exec_script, command, _coerce_exec_script_args(args), comment)


def recognitionMimic(*args) -> None:
    """Mimic a recognition with the given word list.

    Accepts either a list: recognitionMimic(["a", "b"])
    or varargs: recognitionMimic("a", "b")
    """
    _require_connected()
    _require_not_during_init("recognitionMimic")
    _require_not_paused("recognitionMimic")
    com_call("recognitionMimic", _state.backend.recognition_mimic, _coerce_mimic_words(args))
