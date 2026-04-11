"""Action notification sink for playback/script completion callbacks.

"This is a playback notification sink."
-- Joel Gould, DragonCode.cpp line 387

Implements IDgnSSvcActionNotifySink: PlaybackDone, ExecutionDone, etc.

Matches C++ CDgnSSvcActionNotifySink (DragonCode.cpp line 390): each
callback PostMessages to the hidden window with dwClientCode as wParam.
The caller's message_loop matches via TriggerMessage(wParam == clientCode).

  PlaybackDone     -> WM_PLAYBACK  (wParam=code, lParam=0)
  PlaybackAborted  -> WM_PLAYBACK  (wParam=code, lParam=1)
  ExecutionDone    -> WM_EXECUTION (wParam=code, lParam=0)
  ExecutionAborted -> WM_EXECUTION (wParam=code, lParam=(LPARAM)pData)

In the C++ original, ExecutionAborted passes a heap-allocated DWORD[2]
holding {eCode, iLineNumber} as lParam.  In this Python port we stash a
formatted error string and pass the stash key instead.
"""

import logging

log = logging.getLogger("natlink.com.sink.action")

from ._com_helpers import lazy_com_factory


def _build_sink_class():
    """Build the ActionSink COMObject class."""
    from comtypes import COMObject
    tlb = __import__('natlink_com._tlb', fromlist=['get_tlb']).get_tlb()
    IDgnSSvcActionNotifySink = tlb.IDgnSSvcActionNotifySink
    IDgnGetSinkFlags = tlb.IDgnGetSinkFlags
    from . import _hidden_wnd

    class ActionSink(COMObject):
        """Playback/script completion sink.

        PostMessage matching C++ CDgnSSvcActionNotifySink:
          PlaybackDone     → PostMessage(WM_PLAYBACK, dwClientCode, 0)
          PlaybackAborted  → PostMessage(WM_PLAYBACK, dwClientCode, 1)
          ExecutionDone    → PostMessage(WM_EXECUTION, dwClientCode, 0)
          ExecutionAborted → PostMessage(WM_EXECUTION, dwClientCode, stash_key)
        """
        _com_interfaces_ = [IDgnSSvcActionNotifySink, IDgnGetSinkFlags]

        def __init__(self):
            super().__init__()
            self._conn = None  # set by DragonConnection after creation

        # --- IDgnGetSinkFlags ---

        def IDgnGetSinkFlags_SinkFlagsGet(self, p0):
            return 0

        # --- IDgnSSvcActionNotifySink ---

        def IDgnSSvcActionNotifySink_PlaybackDone(self, dwClientCode):
            log.debug("PlaybackDone(code=%d)", dwClientCode)
            _hidden_wnd.post(_hidden_wnd.WM_PLAYBACK, dwClientCode, 0)
            return 0

        def IDgnSSvcActionNotifySink_PlaybackAborted(self, dwClientCode, hrReason):
            # "note that the current Dragon NaturallySpeaking does not generate
            # any meaningful error codes so we just pass some non-zero value"
            # -- Joel Gould, DragonCode.cpp line 436-437
            log.warning("PlaybackAborted(code=%d, hr=0x%08X)",
                        dwClientCode, hrReason & 0xFFFFFFFF)
            _hidden_wnd.post(_hidden_wnd.WM_PLAYBACK, dwClientCode, 1)
            return 0

        def IDgnSSvcActionNotifySink_ExecutionDone(self, dwClientCode):
            log.debug("ExecutionDone(code=%d)", dwClientCode)
            _hidden_wnd.post(_hidden_wnd.WM_EXECUTION, dwClientCode, 0)
            return 0

        def IDgnSSvcActionNotifySink_ExecutionStatus(self, dwClientCode, dwStatus):
            # "This callback occurs when a script is being executed and the
            # script includes a command which changes the state of the script.
            # Currently the possible status buts are:
            #
            #   ACTIONSTATUS_F_ALLOWHEARDWORD which means that the script
            #       includes a HeardWord command (same as RecognitionMimic)
            #       which means that we need to unpause recognition
            #
            #   ACTIONSTATUS_F_ALLOWUSERINPUT which means that the script is
            #       displaying a message box which also means that we need to
            #       unpause recognition"
            # -- Joel Gould, DragonCode.cpp lines 459-469
            log.debug("ExecutionStatus(code=%d, status=0x%X)",
                      dwClientCode, dwStatus)
            if dwStatus != 0 and self._conn is not None:
                self._conn.reset_pause_recog()
            return 0

        def IDgnSSvcActionNotifySink_ExecutionAborted(self, dwClientCode, hrReason, dwExtra):
            # C++ stores error info as two DWORDs passed via PostMessage lParam:
            #   DWORD * pData = new DWORD[2];
            #   pData[0] = eCode;
            #   pData[1] = iLineNumber;
            #   postMessage(WM_EXECUTION, dwClientCode, (LPARAM)pData);
            # We stash a formatted error string instead and pass the stash key.
            # -- Joel Gould, DragonCode.cpp lines 492-496
            log.warning("ExecutionAborted(code=%d, hr=0x%08X, line=%d)",
                        dwClientCode, hrReason & 0xFFFFFFFF, dwExtra)
            error_msg = (f"Script execution aborted "
                         f"(error 0x{hrReason & 0xFFFFFFFF:08X}, line {dwExtra})")
            key = _hidden_wnd.stash_put(error_msg)
            _hidden_wnd.post(_hidden_wnd.WM_EXECUTION, dwClientCode, key)
            return 0

    return ActionSink


create_action_sink = lazy_com_factory(_build_sink_class)
