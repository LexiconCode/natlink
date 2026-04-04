"""Tests for natlink_compat._monitor — Dragon process lifecycle monitor."""

import threading
import unittest
from unittest import mock

import natlink_compat._monitor as mod


class TestMonitorEvents(unittest.TestCase):
    """Tests for create_events, close_events, _signal_exited, _signal_reappeared."""

    def setUp(self):
        self._saved_exited = mod._h_dragon_exited
        self._saved_reappeared = mod._h_dragon_reappeared

    def tearDown(self):
        mod._h_dragon_exited = self._saved_exited
        mod._h_dragon_reappeared = self._saved_reappeared

    @mock.patch("natlink_compat._monitor.kernel32")
    def test_create_events_calls_create_event_w(self, mock_k32):
        mod._h_dragon_exited = 0
        mod._h_dragon_reappeared = 0
        mock_k32.CreateEventW.side_effect = [0xAA, 0xBB]

        h_exit, h_reappear = mod.create_events()

        self.assertEqual(h_exit, 0xAA)
        self.assertEqual(h_reappear, 0xBB)
        self.assertEqual(mock_k32.CreateEventW.call_count, 2)
        mock_k32.CreateEventW.assert_any_call(
            None, True, False, mod._DRAGON_EXITED_EVENT
        )
        mock_k32.CreateEventW.assert_any_call(
            None, True, False, mod._DRAGON_REAPPEARED_EVENT
        )

    @mock.patch("natlink_compat._monitor.kernel32")
    def test_create_events_idempotent(self, mock_k32):
        mod._h_dragon_exited = 0xAA
        mod._h_dragon_reappeared = 0xBB

        h_exit, h_reappear = mod.create_events()

        self.assertEqual(h_exit, 0xAA)
        self.assertEqual(h_reappear, 0xBB)
        mock_k32.CreateEventW.assert_not_called()

    @mock.patch("natlink_compat._monitor.kernel32")
    def test_close_events_closes_and_resets(self, mock_k32):
        mod._h_dragon_exited = 0xAA
        mod._h_dragon_reappeared = 0xBB

        mod.close_events()

        self.assertEqual(mod._h_dragon_exited, 0)
        self.assertEqual(mod._h_dragon_reappeared, 0)
        mock_k32.CloseHandle.assert_any_call(0xAA)
        mock_k32.CloseHandle.assert_any_call(0xBB)
        self.assertEqual(mock_k32.CloseHandle.call_count, 2)

    @mock.patch("natlink_compat._monitor.kernel32")
    def test_close_events_safe_when_zero(self, mock_k32):
        mod._h_dragon_exited = 0
        mod._h_dragon_reappeared = 0

        mod.close_events()

        mock_k32.CloseHandle.assert_not_called()

    @mock.patch("natlink_compat._monitor.kernel32")
    def test_signal_exited_calls_set_event(self, mock_k32):
        mod._h_dragon_exited = 0xAA

        mod._signal_exited()

        mock_k32.SetEvent.assert_called_once_with(0xAA)

    @mock.patch("natlink_compat._monitor.kernel32")
    def test_signal_reappeared_calls_set_event(self, mock_k32):
        mod._h_dragon_reappeared = 0xBB

        mod._signal_reappeared()

        mock_k32.SetEvent.assert_called_once_with(0xBB)


class TestGetDragonHandle(unittest.TestCase):
    """Tests for _get_dragon_handle."""

    def setUp(self):
        self._saved_exited = mod._h_dragon_exited
        self._saved_reappeared = mod._h_dragon_reappeared

    def tearDown(self):
        mod._h_dragon_exited = self._saved_exited
        mod._h_dragon_reappeared = self._saved_reappeared

    @mock.patch("natlink_compat._monitor.user32")
    def test_returns_none_when_no_window(self, mock_u32):
        mock_u32.FindWindowW.return_value = 0

        result = mod._get_dragon_handle()

        self.assertIsNone(result)
        mock_u32.FindWindowW.assert_called_once_with(mod.DRAGON_CLS, None)

    @mock.patch("natlink_compat._monitor.kernel32")
    @mock.patch("natlink_compat._monitor.user32")
    def test_returns_handle_on_success(self, mock_u32, mock_k32):
        mock_u32.FindWindowW.return_value = 0x1234
        # GetWindowThreadProcessId writes to the DWORD byref — we simulate
        # by having the mock accept the call; the real ctypes DWORD is created
        # inside _get_dragon_handle so we patch at a higher level.
        def fake_get_pid(hwnd, lp_pid):
            # lp_pid is a ctypes byref object; set .value on the underlying
            import ctypes
            ctypes.cast(lp_pid, ctypes.POINTER(ctypes.wintypes.DWORD)).contents.value = 42

        mock_u32.GetWindowThreadProcessId.side_effect = fake_get_pid
        mock_k32.OpenProcess.return_value = 0xDEAD

        result = mod._get_dragon_handle()

        self.assertEqual(result, 0xDEAD)
        mock_k32.OpenProcess.assert_called_once_with(mod.SYNCHRONIZE, False, 42)


class TestStartDragonMonitor(unittest.TestCase):
    """Tests for start_dragon_monitor."""

    def setUp(self):
        self._saved_exited = mod._h_dragon_exited
        self._saved_reappeared = mod._h_dragon_reappeared

    def tearDown(self):
        mod._h_dragon_exited = self._saved_exited
        mod._h_dragon_reappeared = self._saved_reappeared

    @mock.patch("natlink_compat._monitor.kernel32")
    @mock.patch("natlink_compat._monitor.user32")
    def test_starts_daemon_thread(self, mock_u32, mock_k32):
        mod._h_dragon_exited = 0xAA
        mod._h_dragon_reappeared = 0xBB

        state = mock.MagicMock()
        state.monitor_stop_event = threading.Event()
        state.connected = False
        # Signal stop immediately so the thread exits fast
        state.monitor_stop_event.set()

        mod.start_dragon_monitor(state)

        state.set_monitor_thread.assert_called_once()
        thread = state.set_monitor_thread.call_args[0][0]
        self.assertTrue(thread.daemon)
        self.assertEqual(thread.name, "dragon-monitor")
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    @mock.patch("natlink_compat._monitor.kernel32")
    @mock.patch("natlink_compat._monitor.user32")
    def test_signals_exited_when_connected_no_dragon(self, mock_u32, mock_k32):
        """When connected but Dragon window is gone, should signal exited."""
        mod._h_dragon_exited = 0xAA
        mod._h_dragon_reappeared = 0xBB

        state = mock.MagicMock()
        stop = threading.Event()
        state.monitor_stop_event = stop
        state.connected = True

        # FindWindowW returns 0 => no Dragon window
        mock_u32.FindWindowW.return_value = 0

        mod.start_dragon_monitor(state)
        # Give the thread a moment to execute, then stop it
        import time
        time.sleep(0.2)
        stop.set()

        thread = state.set_monitor_thread.call_args[0][0]
        thread.join(timeout=2)

        # _signal_exited should have called SetEvent on the exited handle
        mock_k32.SetEvent.assert_any_call(0xAA)


if __name__ == "__main__":
    unittest.main()
