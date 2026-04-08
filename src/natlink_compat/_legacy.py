"""_legacy.py - No-op stubs for removed natlink APIs.

These functions exist solely so existing code (natlinkcore, third-party
grammars) that calls them doesn't raise AttributeError.  Each stub
silently accepts its original arguments and does nothing.

The import in __init__.py re-exports them under their original names.
"""

from typing import Callable, Optional


def setMessageWindow(callback: Optional[Callable] = None, flags: int = 0) -> None:
    """Enable, disable, or update natlink's message window.

    In the original C extension, this controlled a Win32 message window
    with File>Reload and File>Exit menu items. In the current out-of-process
    architecture, the output window is managed by the UI provider and this
    function is accepted for backwards compatibility only.

    Args:
        callback: A function accepting one parameter (the event type:
            ``idd_reload`` or ``idd_exit``), or ``None`` to disable.
        flags: Optional combination of:

            - ``0x01`` — enable the File>Exit menu item
            - ``0x02`` — disable the File>Reload menu item
            - ``0x04`` — disable the menu entirely
    """


def displayText(text: str, isError: bool = False, logText: bool = True) -> None:
    """Append a message to the natlink output window.

    In the original C extension, this displayed text in a dedicated Win32
    window (red for errors, black for normal text). In the current
    out-of-process architecture, stdout/stderr redirection is handled by
    the logging subsystem. This shim writes to the real console streams
    for any third-party code that calls ``natlink.displayText()`` directly.

    Args:
        text: The text to display.
        isError: If True, treat as error output (writes to stderr).
        logText: If True, also copy the text to the Dragon log file
            (not implemented in this shim).
    """
    import sys
    stream = sys.__stderr__ if isError else sys.__stdout__
    if stream is not None:
        stream.write(text)
