"""Example entry_point loader — auto-discovered by natlink on startup.

Install this package with: pip install -e examples/example_entry_point_package

Natlink discovers it via the "natlink.loaders" entry_points group
in pyproject.toml. The lifecycle is:

  1. setup() — called before natConnect, set custom UI providers here
  2. run()   — called during natConnect, register your loader
  3. stop()  — called during natDisconnect

No manual add_loader() call needed — just pip install and go.
"""

import logging
import os

log = logging.getLogger(__name__)

_instance = None


class MyLoader:
    """Loader that prints a message on start/stop."""

    def __init__(self, config_dir):
        self.config_dir = config_dir

    def start(self):
        log.info("MyLoader started (config: %s)", self.config_dir)
        # Load your grammars here...

    def stop(self):
        log.info("MyLoader stopped")
        # Unload your grammars here...


def setup():
    """Called after import, before natConnect — set custom UI here.

    Example:
        import natlink
        natlink.set_ui_provider(MyCustomUI())
    """
    pass  # This loader uses the default UI


def run():
    """Called during natConnect — register your loader."""
    import natlink

    global _instance
    config_dir = os.path.expanduser("~/.my-natlink-loader")
    _instance = MyLoader(config_dir)
    natlink.add_loader(_instance)


def stop():
    """Fallback stop — called if natlink stops the module directly."""
    global _instance
    if _instance:
        _instance.stop()
        _instance = None
