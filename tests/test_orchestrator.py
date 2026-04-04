"""test_orchestrator.py - Unit tests for natlink_compat._orchestrator.

Tests orchestrator logic: provider discovery, connect sequences, restart guard.
Does NOT require Dragon — all COM/launcher calls are mocked.
"""

import threading
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestDiscoverUIProvider(unittest.TestCase):

    @patch("importlib.metadata.entry_points", return_value=[])
    def test_no_entry_points_falls_back_to_natlink_ui(self, mock_eps):
        with patch("natlink_ui.UIProvider") as MockUI:
            mock_instance = MagicMock()
            MockUI.return_value = mock_instance

            from natlink_compat._orchestrator import _discover_ui_provider
            provider = _discover_ui_provider()
            self.assertIs(provider, mock_instance)

    @patch("importlib.metadata.entry_points", return_value=[])
    def test_no_entry_points_no_natlink_ui_returns_none(self, mock_eps):
        from natlink_compat._orchestrator import _discover_ui_provider
        with patch("natlink_compat._orchestrator.log"):
            # Make the natlink_ui import fail
            import builtins
            real_import = builtins.__import__
            def fake_import(name, *args, **kwargs):
                if name == "natlink_ui":
                    raise ImportError("no natlink_ui")
                return real_import(name, *args, **kwargs)
            with patch("builtins.__import__", side_effect=fake_import):
                provider = _discover_ui_provider()
                self.assertIsNone(provider)

    def test_entry_point_loaded(self):
        mock_ep = MagicMock()
        mock_ep.name = "custom_ui"
        mock_ep.value = "my_package:MyUI"
        mock_provider = MagicMock()
        mock_ep.load.return_value = lambda: mock_provider

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            from natlink_compat._orchestrator import _discover_ui_provider
            provider = _discover_ui_provider()
            self.assertIs(provider, mock_provider)

    def test_failing_entry_point_falls_through(self):
        mock_ep = MagicMock()
        mock_ep.name = "bad_ui"
        mock_ep.value = "bad:UI"
        mock_ep.load.side_effect = RuntimeError("broken")

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            with patch("natlink_ui.UIProvider") as MockUI:
                mock_instance = MagicMock()
                MockUI.return_value = mock_instance

                from natlink_compat._orchestrator import _discover_ui_provider
                provider = _discover_ui_provider()
                self.assertIs(provider, mock_instance)

    def test_non_default_entry_point_takes_priority(self):
        custom_ep = MagicMock()
        custom_ep.name = "custom_ui"
        custom_ep.value = "custom:UI"
        custom_provider = MagicMock(name="custom_provider")
        custom_ep.load.return_value = lambda: custom_provider

        default_ep = MagicMock()
        default_ep.name = "default"
        default_ep.value = "natlink_ui:UIProvider"
        default_provider = MagicMock(name="default_provider")
        default_ep.load.return_value = lambda: default_provider

        with patch("importlib.metadata.entry_points", return_value=[default_ep, custom_ep]):
            from natlink_compat._orchestrator import _discover_ui_provider
            provider = _discover_ui_provider()

        self.assertIs(provider, custom_provider)

    def test_direct_import_fallback_returns_single_provider(self):
        with patch("importlib.metadata.entry_points", return_value=[]):
            with patch("natlink_ui.UIProvider") as MockUI:
                mock_instance = MagicMock()
                MockUI.return_value = mock_instance

                from natlink_compat._orchestrator import _discover_ui_provider
                provider = _discover_ui_provider()

        self.assertIs(provider, mock_instance)


class TestRestartLock(unittest.TestCase):
    """Test the restart lock prevents concurrent restarts."""

    def test_restart_lock_blocks_concurrent(self):
        from natlink_compat._orchestrator import _restart_lock

        # Acquire the lock
        acquired = _restart_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            # Second acquire should fail (non-blocking)
            second = _restart_lock.acquire(blocking=False)
            self.assertFalse(second)
        finally:
            _restart_lock.release()

    def test_restart_lock_released_after(self):
        from natlink_compat._orchestrator import _restart_lock

        _restart_lock.acquire(blocking=False)
        _restart_lock.release()

        # Should be acquirable again
        acquired = _restart_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        _restart_lock.release()


class TestProbeAndWait(unittest.TestCase):

    @patch("natlink_compat._orchestrator._wait_for_profile_via_log")
    @patch("natlink_compat._orchestrator._wait_for_com_ready")
    @patch("natlink_compat._orchestrator._wait_for_dragon_window", return_value=True)
    def test_full_probe(self, mock_window, mock_com, mock_profile):
        from natlink_compat._orchestrator import _probe_and_wait
        result = _probe_and_wait(wait_for_window=True, wait_for_profile=True)
        self.assertTrue(result)
        mock_window.assert_called_once()
        mock_com.assert_called_once()
        mock_profile.assert_called_once()

    @patch("natlink_compat._orchestrator._wait_for_com_ready")
    @patch("natlink_compat._orchestrator._wait_for_dragon_window", return_value=False)
    def test_probe_shutdown_during_window_wait(self, mock_window, mock_com):
        from natlink_compat._orchestrator import _probe_and_wait
        result = _probe_and_wait(wait_for_window=True, wait_for_profile=True)
        self.assertFalse(result)
        mock_com.assert_not_called()

    @patch("natlink_compat._orchestrator._wait_for_com_ready")
    def test_probe_skip_window_wait(self, mock_com):
        from natlink_compat._orchestrator import _probe_and_wait
        result = _probe_and_wait(wait_for_window=False, wait_for_profile=False)
        self.assertTrue(result)
        mock_com.assert_called_once()


class TestConnect(unittest.TestCase):

    def test_connect_success(self):
        from natlink_compat._orchestrator import _connect
        mock_natlink = MagicMock()
        result = _connect(mock_natlink)
        self.assertTrue(result)
        mock_natlink.natConnect.assert_called_once()

    def test_connect_failure(self):
        from natlink_compat._orchestrator import _connect
        mock_natlink = MagicMock()
        mock_natlink.natConnect.side_effect = RuntimeError("COM error")
        result = _connect(mock_natlink)
        self.assertFalse(result)


class TestWaitForExit(unittest.TestCase):

    def test_exits_immediately(self):
        from natlink_compat._orchestrator import _wait_for_exit
        result = _wait_for_exit(lambda: False, timeout=1)
        self.assertTrue(result)

    def test_timeout(self):
        from natlink_compat._orchestrator import _wait_for_exit
        # Always running — will timeout. Use timeout=1 to keep test fast.
        with patch("time.sleep"):  # Skip actual sleeps
            result = _wait_for_exit(lambda: True, timeout=1)
        self.assertFalse(result)


class TestHandleDragonReappeared(unittest.TestCase):

    @patch("natlink_compat._orchestrator._connect")
    @patch("natlink_compat._orchestrator._probe_and_wait", return_value=True)
    def test_reconnects_when_disconnected(self, mock_probe, mock_connect):
        from natlink_compat._orchestrator import _handle_dragon_reappeared
        from natlink_compat._state import _state
        _state.reset()

        mock_natlink = MagicMock()
        _handle_dragon_reappeared(mock_natlink)

        mock_probe.assert_called_once()
        mock_connect.assert_called_once_with(mock_natlink)

    @patch("natlink_compat._orchestrator._probe_and_wait")
    def test_skips_when_already_connected(self, mock_probe):
        from natlink_compat._orchestrator import _handle_dragon_reappeared
        from natlink_compat._state import _state
        _state.reset()
        # connected is a property derived from backend — set backend to make it True
        _state.backend = MagicMock()

        mock_natlink = MagicMock()
        _handle_dragon_reappeared(mock_natlink)

        mock_probe.assert_not_called()
        _state.reset()
