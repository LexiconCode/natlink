"""Pluggable loader protocol for natlink.

Third-party loaders (e.g. natlinkcore) implement this protocol.
Discovery order: runtime add_loader() > entry_points.
Multiple loaders can be active simultaneously.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class LoaderProtocol(Protocol):
    """Contract for natlink loader plugins.

    A loader manages grammar discovery and hot-reload for a set of
    user directories.  It is started after natConnect() succeeds and
    stopped before natDisconnect() tears down COM.

    Implementations may be either class instances or modules with
    module-level start()/stop() functions.
    """

    def start(self) -> None:
        """Begin watching directories and loading grammars."""
        ...

    def stop(self) -> None:
        """Unload all grammars and stop watching."""
        ...
