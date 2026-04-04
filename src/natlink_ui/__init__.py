"""natlink_ui — default Win32 tray UI for natlink.

Implements the natlink_compat UIProvider protocol with a system tray
icon and RichEdit output window. Serves as both the shipping default
and a reference implementation for third-party UI providers.

Entry point registration (pyproject.toml)::

    [project.entry-points."natlink.ui_provider"]
    default = "natlink_ui:UIProvider"

Third parties replace by registering their own entry point with
a non-"default" name.
"""

import logging
import os
import threading

import natlink_compat
from natlink_compat import (
    NatlinkState,
    PHASE_IDLE, PHASE_WAITING_FOR_DRAGON, PHASE_CONNECTING,
    PHASE_LOADING_PROFILE, PHASE_CONNECTED, PHASE_RESTARTING, PHASE_ERROR,
)

log = logging.getLogger("natlink.ui")

_ICON_MAP = {
    PHASE_CONNECTED: "connected",
    PHASE_ERROR: "error",
}

_TOOLTIPS = {
    PHASE_IDLE: "Natlink - Disconnected",
    PHASE_WAITING_FOR_DRAGON: "Natlink - Waiting for Dragon",
    PHASE_CONNECTING: "Natlink - Connecting...",
    PHASE_LOADING_PROFILE: "Natlink - Loading profile...",
    PHASE_CONNECTED: "Natlink - Connected",
    PHASE_RESTARTING: "Natlink - Restarting Dragon...",
    PHASE_ERROR: "Natlink - {error}",
}


class UIProvider:
    """Default UIProvider — Win32 tray icon + RichEdit output window.

    Also provides app-specific features: startup shortcut management,
    show-on-error behavior, config/log file opening. These extras are
    not part of the UIProvider protocol — they're implementation details
    of the default UI that third parties don't need to replicate.
    """

    def __init__(self):
        from ._config import load as load_ui_config, save as save_ui_config
        from ._window import NatlinkWindow

        self._lock = threading.Lock()
        self._window = NatlinkWindow(
            load_config=load_ui_config, save_config=save_ui_config)
        self._build_menu()
        self._window.show_tray_icon(tooltip="Natlink", icon_name="disconnected")
        self._started = True
        if self._is_show_messages_enabled():
            self._window.show()

    # --- UIProvider protocol ---

    def on_state_changed(self, state: NatlinkState) -> None:
        icon = _ICON_MAP.get(state.phase, "disconnected")
        tooltip = _TOOLTIPS.get(state.phase, "Natlink")
        if state.phase == PHASE_ERROR and state.error_message:
            tooltip = tooltip.format(error=state.error_message)
        self._window.show_tray_icon(tooltip, icon)

    def on_text(self, text: str, level: int = logging.INFO) -> None:
        self._window.write(text, level >= logging.WARNING)
        if level >= logging.ERROR and not self._window.is_visible:
            if self._is_show_on_error_enabled():
                self._window.show()

    # --- Optional UIProvider extensions ---

    def show_output(self):
        self._window.show()

    def hide_output(self):
        self._window.hide()

    def clear_output(self):
        self._window.clear()

    def stop(self):
        with self._lock:
            if self._started:
                self._window.destroy_safe()
                self._started = False

    # --- UI-specific settings (stored in natlink_ui.ini) ---

    @staticmethod
    def _is_show_messages_enabled():
        from ._config import get_bool
        return get_bool("settings", "show_messages_on_startup", fallback=True)

    @staticmethod
    def _is_show_on_error_enabled():
        from ._config import get_bool
        return get_bool("settings", "show_on_error", fallback=False)

    @staticmethod
    def _toggle_show_messages():
        from ._config import toggle_bool
        toggle_bool("settings", "show_messages_on_startup", fallback=True)

    @staticmethod
    def _toggle_show_on_error():
        from ._config import toggle_bool
        toggle_bool("settings", "show_on_error", fallback=False)

    # --- Desktop file-opening actions ---

    @staticmethod
    def _open_config():
        from ._config import _get_store
        path = _get_store().path
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        os.startfile(path)

    @staticmethod
    def _open_natlink_log():
        import natlink_compat
        log_path = natlink_compat.get_log_path()
        if log_path.is_file():
            os.startfile(log_path)

    @staticmethod
    def _open_dragon_log():
        import natlink_compat
        base = natlink_compat.get_dragon_log_dir()
        if base is None:
            return
        os.startfile(base)

    # --- Shortcuts (delegate to _shortcuts module) ---

    @staticmethod
    def toggle_startup():
        from . import _shortcuts
        if _shortcuts.is_startup_installed():
            _shortcuts.uninstall_startup()
        else:
            _shortcuts.install_startup()

    @staticmethod
    def is_startup_installed():
        from . import _shortcuts
        return _shortcuts.is_startup_installed()

    # --- Menu ---

    def _toggle_topmost(self):
        self._window.set_topmost(not self._window.is_topmost)

    def _build_menu(self):
        w = self._window

        w.add_submenu("Message Window", [
            ("Show", self._window.show, None),
            ("Hide", self._window.hide, None),
            ("Clear", self._window.clear, None),
            ("Always on Top", self._toggle_topmost, lambda: self._window.is_topmost),
        ])

        w.add_separator()
        w.add_submenu("Logs", [
            ("Natlink Log", self._open_natlink_log, None),
            ("Dragon Log", self._open_dragon_log, None),
            None,
            ("submenu", "Natlink Level", [
                ("DEBUG", lambda: natlink_compat.set_log_level(logging.DEBUG), lambda: natlink_compat.get_log_level() == logging.DEBUG),
                ("INFO", lambda: natlink_compat.set_log_level(logging.INFO), lambda: natlink_compat.get_log_level() == logging.INFO),
                ("WARNING", lambda: natlink_compat.set_log_level(logging.WARNING), lambda: natlink_compat.get_log_level() == logging.WARNING),
                ("ERROR", lambda: natlink_compat.set_log_level(logging.ERROR), lambda: natlink_compat.get_log_level() == logging.ERROR),
            ]),
        ])

        w.add_separator()
        loader_items = [("Reload Grammars", lambda: natlink_compat.reload_grammars(), None)]
        states = natlink_compat.get_loader_states()
        if states:
            loader_items.append(None)
        for name, _enabled in states:
            loader_items.append(
                (name,
                 (lambda n: lambda: natlink_compat.toggle_loader(n))(name),
                 (lambda n: lambda: dict(natlink_compat.get_loader_states()).get(n, True))(name)))
        w.add_submenu("Loaders", loader_items)

        w.add_submenu("Configure", [
            ("Edit Config", self._open_config, None),
            ("Run at Startup", self.toggle_startup, self.is_startup_installed),
            ("Auto-launch Dragon", lambda: natlink_compat.toggle_auto_launch(), lambda: natlink_compat.is_auto_launch_enabled()),
            ("Show Messages on Startup", self._toggle_show_messages, self._is_show_messages_enabled),
            ("Show on Error", self._toggle_show_on_error, self._is_show_on_error_enabled),
        ])

        w.add_separator()

        def _dragon_label():
            return "Restart Dragon" if natlink_compat.is_dragon_running() else "Launch Dragon"

        def _dragon_action():
            if natlink_compat.is_dragon_running():
                natlink_compat.restart_dragon()
            else:
                natlink_compat.start_dragon()

        w.add_menu_item(_dragon_label, _dragon_action)
        w.add_menu_item("Exit", lambda: natlink_compat.exit_natlink())


# ---------------------------------------------------------------------------
# Module-level UI control — import natlink_ui; natlink_ui.show_output()
# ---------------------------------------------------------------------------

def _get_provider():
    """Return our UIProvider from the active provider slot, or None."""
    import natlink_compat
    provider = natlink_compat.get_ui_provider()
    if isinstance(provider, UIProvider):
        return provider
    return None


def show_output():
    p = _get_provider()
    if p is not None:
        p.show_output()


def hide_output():
    p = _get_provider()
    if p is not None:
        p.hide_output()


def clear_output():
    p = _get_provider()
    if p is not None:
        p.clear_output()


# ---------------------------------------------------------------------------
# UI install/uninstall
# ---------------------------------------------------------------------------

def bootstrap_config() -> int:
    """Configure runtime if possible."""
    cfg = natlink_compat.configure_runtime()
    if not cfg.has_section("dragon"):
        print("Dragon NaturallySpeaking not found.\n"
              "Install Dragon first, then run: natlink-ui")
        return 1

    from natlink_com._config import _print_config
    _print_config(cfg)
    return 0


def install_ui(*, startup: bool = False) -> int:
    """Configure runtime and install default UI integration."""
    from natlink_com._launcher import request_shutdown
    from . import _shortcuts

    # Stop running natlink instance to avoid config/shortcut conflicts
    if request_shutdown():
        print("Stopped running natlink instance.")

    rc = bootstrap_config()
    if rc:
        return rc

    desktop_ok = _shortcuts.create_desktop_shortcut()
    startup_ok = True
    if startup:
        startup_ok = _shortcuts.install_startup()

    if not desktop_ok:
        print("Warning: desktop shortcut was not created.")
    if startup and not startup_ok:
        print("Warning: startup shortcut was not created.")

    print("\nNatlink configured. Run 'natlink start' to launch.")
    return 0


def uninstall_ui(*, remove_config: bool = True) -> int:
    """Remove default UI integration and optionally natlink.ini."""
    from natlink_com._launcher import request_shutdown
    from . import _shortcuts

    if request_shutdown():
        print("Natlink stopped.")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        natlink_compat.stop_dragon()
    except Exception:
        print("Warning: could not stop Dragon (it may not be running)")

    _shortcuts.uninstall_startup()
    _shortcuts.remove_desktop_shortcut()

    if remove_config:
        config_path = natlink_compat.get_config_path()
        try:
            natlink_compat.remove_runtime_config()
            print(f"Removed: {config_path}")
        except OSError as exc:
            print(f"Could not remove {config_path}: {exc}")
            return 1
    return 0


def cli_main() -> None:
    """Console entry point for UI-owned install and uninstall."""
    import argparse

    parser = argparse.ArgumentParser(prog="natlink-ui", description="Natlink UI setup")
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Configure natlink and install UI shortcuts")
    install_parser.add_argument("--startup", action="store_true", help="Install a Windows Startup shortcut")

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove UI shortcuts and natlink configuration")
    uninstall_parser.add_argument(
        "--keep-config",
        action="store_true",
        help="Remove UI integration but leave natlink.ini in place",
    )

    args = parser.parse_args()
    if args.command == "install":
        raise SystemExit(install_ui(startup=args.startup))
    if args.command == "uninstall":
        raise SystemExit(uninstall_ui(remove_config=not args.keep_config))
    parser.print_help()


# ---------------------------------------------------------------------------
# Entry point — natlink-ui GUI launcher
# ---------------------------------------------------------------------------

def main():
    """GUI entry point for natlink-ui. No console window."""
    import argparse
    import ctypes

    parser = argparse.ArgumentParser(prog="natlink-ui")
    parser.add_argument("--install-shortcuts", action="store_true",
                        help="Configure natlink and create the desktop shortcut")
    parser.add_argument("--startup", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--keep-config", action="store_true")
    args, _unknown = parser.parse_known_args()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    import natlink_compat
    if args.uninstall:
        raise SystemExit(uninstall_ui(remove_config=not args.keep_config))
    if args.install_shortcuts or args.startup:
        raise SystemExit(install_ui(startup=args.startup))

    if not natlink_compat.is_configured():
        if bootstrap_config():
            from ._win32 import msgbox, MB_ICONERROR
            msgbox("Natlink is not configured.\n"
                   "Install Dragon first, then run natlink-ui again.",
                   "Natlink", MB_ICONERROR)
            return

    try:
        natlink_compat.configure()
        natlink_compat.run()
    except Exception:
        import traceback
        from ._win32 import msgbox, MB_ICONERROR
        msgbox(traceback.format_exc(), "Natlink — Failed to start", MB_ICONERROR)
