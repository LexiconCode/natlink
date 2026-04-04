"""_system.py - System info and utility functions."""

import struct
from typing import List, Optional, Sequence, Tuple

from ._helpers import _require_connected, _require_not_during_init, _require_not_paused, com_call
from ._state import _state
from natlink_com._dspeech_constants import DGNUTTFLG_DETECTUTT, DGNUTTFLG_REALTIME

# Re-entrancy guard for inputFromFile — matches C++ CInFunction/bInFunction.
# "We do not allow playback if we are already in the middle of playback.
# This is really a limitation of NatSpeak because there can only be one
# active file-based audio source."
# — Joel Gould, DragonCode.cpp (inputFromFile)
_in_input_from_file = False


def getClipboard() -> str:
    """Get the current clipboard text."""
    _require_connected()
    return com_call("getClipboard", _state.backend.get_clipboard)


def getCursorPos() -> Tuple[int, int]:
    """Get the mouse cursor position as (x, y)."""
    _require_connected()
    return com_call("getCursorPos", _state.backend.get_cursor_pos)


def getScreenSize() -> Tuple[int, int]:
    """Get the screen size as (width, height)."""
    _require_connected()
    return com_call("getScreenSize", _state.backend.get_screen_size)


def getCurrentModule() -> Tuple[str, str, int]:
    """Get the foreground module as (path, title, hwnd)."""
    _require_connected()
    return com_call("getCurrentModule", _state.backend.get_current_module)


def getCurrentUser() -> Tuple[str, str]:
    """Get the current Dragon user as (name, directory)."""
    _require_connected()
    return com_call("getCurrentUser", _state.backend.get_current_user)


def getMicState() -> str:
    """Get the microphone state: 'on', 'off', or 'sleeping'."""
    _require_connected()
    return com_call("getMicState", _state.backend.get_mic_state)


def setMicState(newState: str) -> None:
    """Set the microphone state: 'on', 'off', or 'sleeping'."""
    _require_connected()
    com_call("setMicState", _state.backend.set_mic_state, newState)


def inputFromFile(fileName: str, realtime: int = 0,
                  playlist: Sequence = None,
                  uttDetect: int = -1) -> None:
    """Play audio from a file into the recognizer.

    Args:
        fileName: Path to the audio file.
        realtime: If non-zero, play in real time.
        playlist: Optional list of (start, end) sample pairs.
        uttDetect: Utterance detection: 1=on, 0=off, -1=auto (on for WAV).
    """
    _require_connected()
    _require_not_during_init("inputFromFile")
    _require_not_paused("inputFromFile")

    global _in_input_from_file
    if _in_input_from_file:
        from ._exceptions import NatError
        raise NatError("inputFromFile cannot be reentered, "
                       "input is already active")
    _in_input_from_file = True
    try:
        _inputFromFile_impl(fileName, realtime, playlist, uttDetect)
    finally:
        _in_input_from_file = False


_VALID_EXTENSIONS = {'.utd', '.utt', '.utb', '.wav', '.nwv'}


def _testFileName(fileName):
    """Validate audio file before sending to Dragon.

    Matches C++ CDragonCode::testFileName — checks file exists and has
    a legal extension (.utd, .utt, .utb, .wav, .nwv).
    """
    import os
    from ._exceptions import NatError
    if not fileName:
        raise ValueError("inputFromFile: empty filename")
    if not os.path.isfile(fileName):
        raise NatError(
            f"The file named {fileName} does not exist or cannot be opened "
            f"(calling natlink.inputFromFile)")
    ext = os.path.splitext(fileName)[1].lower()
    if ext not in _VALID_EXTENSIONS:
        raise NatError(
            f"The file named {fileName} does not have a legal extension "
            f"(calling natlink.inputFromFile)")


def _inputFromFile_impl(fileName, realtime, playlist, uttDetect):
    _testFileName(fileName)

    # Compute flags
    flags = 0
    is_wav = fileName.lower().endswith(('.wav', '.wave'))
    if uttDetect == 1 or (uttDetect != 0 and is_wav):
        flags |= DGNUTTFLG_DETECTUTT
    if realtime:
        flags |= DGNUTTFLG_REALTIME

    playlist_bytes = _build_playlist(playlist) if playlist else b""

    com_call(
        "inputFromFile",
        _state.backend.input_from_file,
        fileName,
        flags=flags,
        playlist=playlist_bytes,
    )


def getCallbackDepth() -> int:
    """Get the current callback nesting depth.

    Callback depth is tracked locally in _state.callback_depth, incremented
    on entry to each callback dispatch and decremented on exit.

    "The natlinkmain program is also written to avoid reloading changed
    Python modules during a nested callback.  It uses the
    getCallbackDepth function to make this test."
    — Joel Gould, DragonCode.cpp (nested callback design notes)
    """
    return _state.callback_depth


def _build_playlist(playlist):
    """Convert a playlist sequence into raw DWORD-pair bytes.

    Each item is either (start, end) or a single sample offset
    (treated as a single-sample range).
    """
    if not isinstance(playlist, (list, tuple)):
        raise TypeError("inputFromFile requires a play list of integers")

    buf = bytearray()
    for item in playlist:
        if isinstance(item, (list, tuple)):
            if len(item) != 2:
                raise TypeError(
                    "the ranges in the play list passed to inputFromFile must contain integers")
            try:
                start = int(item[0])
                end = int(item[1])
            except Exception as exc:
                raise TypeError(
                    "the ranges in the play list passed to inputFromFile must contain integers") from exc
            if start > end:
                raise TypeError(
                    "end point less than start point in the play list passed to inputFromFile")
            buf += struct.pack("<II", start, end)
        else:
            try:
                value = int(item)
            except Exception as exc:
                raise TypeError(
                    "the play list passed to inputFromFile must contain integers") from exc
            buf += struct.pack("<II", value, value)
    return bytes(buf)
