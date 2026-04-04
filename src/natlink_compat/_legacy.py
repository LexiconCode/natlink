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
