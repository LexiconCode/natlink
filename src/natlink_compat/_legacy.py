"""_legacy.py - No-op stubs for removed natlink APIs.

These functions exist solely so existing code (natlinkcore, third-party
grammars) that calls them doesn't raise AttributeError.  Each stub
silently accepts its original arguments and does nothing.

The import in __init__.py re-exports them under their original names.
"""

from typing import Callable, Optional


def setMessageWindow(callback: Optional[Callable] = None, flags: int = 0) -> None:
    """Accepted for backwards compatibility; has no effect.

    The output window and menu actions are now handled by the UI provider.
    """


def displayText(text: str, isError: bool = False, logText: bool = True) -> None:
    """Legacy shim — prints to the real console streams.

    stdout/stderr redirect is now owned by _logging_setup.py and routes
    through notify_text directly.  This stub exists only for third-party
    code that calls natlink.displayText() explicitly.
    """
    import sys
    stream = sys.__stderr__ if isError else sys.__stdout__
    if stream is not None:
        stream.write(text)
