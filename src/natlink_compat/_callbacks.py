"""_callbacks.py - Notification dispatch for COM callbacks.

STA mode: Dragon COM callbacks are serialized on the main thread.
The sinks post to the deferred queue to avoid blocking the COM callback
(PhraseFinish must return before recognition can restart).

This module provides:
  - register_all() / unregister_all(): wire/unwire callback slots
  - setBeginCallback / setChangeCallback / setTimerCallback: public API
  - _on_paused / _on_attrib_changed: compat-layer handlers
  - dispatch_*: functions that fire user-registered Python callbacks
"""

import logging
import time
from contextlib import contextmanager

from ._state import _state
from ._res_obj import ResObj

log = logging.getLogger("natlink.callbacks")

from natlink_com._dspeech_constants import DGNSRAC_MICSTATE
from natlink_com._speech_constants import (
    ISRNSAC_SPEAKER,
    ISRNOTEFIN_RECOGNIZED,
    ISRNOTEFIN_THISGRAMMAR,
)


@contextmanager
def _callback_trace(name):
    """Context manager that traces callback entry/exit with timing.

    Enter/exit debug lines go to a per-name child logger (e.g.
    ``natlink.callbacks.timer``) so high-frequency callbacks can be
    silenced independently via [Logging.Levels] in natlink.ini.
    Slow-callback warnings stay on the parent logger.
    """
    _state.callback_depth += 1
    depth = _state.callback_depth
    t0 = time.perf_counter()
    child = log.getChild(name)
    child.debug("[%s] enter (depth=%d)", name, depth)
    try:
        yield
    finally:
        _state.callback_depth -= 1
        new_depth = _state.callback_depth
        elapsed_ms = (time.perf_counter() - t0) * 1000
        threshold = _state.slow_callback_ms
        if threshold > 0 and elapsed_ms > threshold:
            log.warning("[%s] SLOW exit (%.1fms > %dms, depth=%d)",
                        name, elapsed_ms, threshold, new_depth)
        else:
            child.debug("[%s] exit (%.1fms, depth=%d)",
                        name, elapsed_ms, new_depth)
        # Replay deferred change callbacks when outermost callback exits.
        # C++ replays BOTH pending speaker and pending mic changes
        # independently (they're separate bits in m_dwPendingCallback).
        #
        # Re-read state before each dispatch because dispatch_change_callback
        # re-enters _callback_trace, whose exit may have already replayed
        # the other pending change via this same code path (chaining).
        if new_depth == 0:
            with _state.lock:
                speaker = _state._pending_speaker
                _state._pending_speaker = None
                mic = _state._pending_micstate
                _state._pending_micstate = None
            if speaker is not None:
                dispatch_change_callback("user", *speaker)
            if mic is not None:
                dispatch_change_callback("mic", mic)


def _slot_handlers():
    """Map of slot-name -> handler. Keys must exactly match the authoritative
    list on ``DragonConnection.CALLBACK_SLOTS``; any mismatch is a bug, raised
    by ``register_all`` rather than silently setting ghost attributes."""
    return {
        "on_paused_dispatch": _on_paused,
        "on_attrib_changed": _on_attrib_changed,
        "on_timer_dispatch": dispatch_timer_callback,
        "on_phrase_finish": dispatch_phrase_finish,
        "on_phrase_hypothesis": dispatch_phrase_hypothesis,
        "on_dict_text_changed": dispatch_dict_text_changed,
        "on_dict_begin": dispatch_dict_begin_callback,
        "lookup_grammar": _lookup_grammar,
    }


def register_all():
    """Wire compat-layer handlers into DragonConnection callback slots.

    Raises if the authoritative ``CALLBACK_SLOTS`` on the com-bridge side
    diverges from this module's handler map (silent drift would drop callbacks).
    """
    backend = _state.backend
    if backend is None:
        return
    conn = backend.conn
    handlers = _slot_handlers()
    expected = set(type(conn).CALLBACK_SLOTS)
    provided = set(handlers.keys())
    if expected != provided:
        missing = expected - provided
        extra = provided - expected
        raise RuntimeError(
            f"callback slot mismatch: missing={sorted(missing)} "
            f"extra={sorted(extra)}")
    for name, handler in handlers.items():
        setattr(conn, name, handler)


def unregister_all():
    """Unwire compat-layer handlers from DragonConnection callback slots."""
    backend = _state.backend
    if backend is None:
        return
    conn = backend.conn
    conn._clear_callback_slots()


def _lookup_grammar(gram_handle):
    """Look up a grammar wrapper by handle (used by ComResObj.get_select_info)."""
    with _state.lock:
        return _state.grammar_registry.get(gram_handle)


# --- Callback dispatch functions (called by COM sinks) ---

def dispatch_begin_callback(module_info):
    """Fire all registered begin callbacks. Called by EngineSink.Paused."""
    if not _state.begin_callbacks:
        return

    with _callback_trace("begin"):
        for cb in list(_state.begin_callbacks):
            try:
                cb(module_info)
            except Exception:
                log.exception("Error in begin callback")


def dispatch_grammar_begin_callback(gram_handle, module_info):
    """Fire per-grammar begin callback. Called by EngineSink.Paused."""
    with _state.lock:
        gram = _state.grammar_registry.get(gram_handle)

    if gram is None:
        return

    cb = getattr(gram, "_begin_callback", None)
    if cb is None:
        return

    with _callback_trace("grammar_begin"):
        try:
            cb(module_info)
        except Exception:
            log.exception("Error in grammar begin callback")


def dispatch_change_callback(change_type, change_value, change_extra=""):
    """Fire the change callback. Called by EngineSink.AttribChanged2.

    "change callbacks are not allowed when we are processing
    another callback, like a begin utterance.  Therefore, we
    defer the change request until later"
    — Joel Gould, DragonCode.cpp (onAttribChanged)
    """
    if not _state.change_callbacks:
        return

    # Defer change callbacks when inside another callback OR during init
    # (matches C++ m_nCallbackDepth || m_bDuringInit guard and
    # PENDING_SPEAKER / PENDING_MICSTATE mechanism).  Each type is stored
    # independently — both can be pending simultaneously.  Replayed
    # when the outermost callback exits (_callback_trace.__exit__).
    if _state.callback_depth > 0 or _state.during_init:
        if change_type == "user":
            _state._pending_speaker = (change_value, change_extra)
        elif change_type == "mic":
            _state._pending_micstate = change_value
        return

    if change_type == "user":
        info = (change_value, change_extra)
    else:
        info = change_value

    with _callback_trace("change"):
        for cb in list(_state.change_callbacks):
            try:
                cb(change_type, info)
            except Exception:
                log.exception("Error in change callback")


def dispatch_timer_callback():
    """Fire all registered timer callbacks.

    Loaders handle their own timer multiplexing (e.g. natlinkcore's
    NatlinkTimer tracks per-grammar intervals internally).

    Skipped if already inside another callback, matching the C++ original:
    "make the Python callback (if we are not in another callback)"
    — Joel Gould, DragonCode.cpp (onTimer)
    """
    if not _state.timer_callbacks:
        return

    if _state.callback_depth > 0:
        return

    with _callback_trace("timer"):
        for cb in list(_state.timer_callbacks):
            try:
                cb()
            except Exception:
                log.exception("Error in timer callback")


def _classify_result(flags, res_obj, gram):
    """Determine result type from flags. Returns details or None to skip.

    "do nothing if the recognition was not for this grammar object and the
    special allResults flag is not set"

    "if this result is a reject or recognition for another grammar then
    create a string object; otherwise, create a list of words object"
    — Joel Gould, GrammarObject.cpp (CGrammarObject::PhraseFinish)
    """
    is_reject = (flags & ISRNOTEFIN_RECOGNIZED) == 0
    is_other = (flags & ISRNOTEFIN_THISGRAMMAR) == 0

    if (is_reject or is_other) and not getattr(gram, "_all_results", False):
        return None  # not relevant and allResults not set

    if is_reject:
        return "reject"
    if is_other:
        return "other"
    try:
        raw = res_obj.get_results(0)
        return [(d.get("word", ""), d.get("cfg_parse", 0)) for d in (raw or [])]
    except Exception:
        log.debug("Could not extract words from result", exc_info=True)
        return []


def dispatch_phrase_finish(gram_handle, flags, res_obj):
    """Fire the results callback. Called by GrammarSink.PhraseFinish.

    In the C++ original, PhraseFinish does not call back into Python
    directly.  Instead it posts WM_SENDRESULTS via makeResultsCallback:

    "setting this will delay recognition at the start of the next
    utterance until results are processed"
    — Joel Gould, DragonCode.cpp (makeResultsCallback)

    When the posted message is handled by onSendResults:

    "now that results are processed, we can resume recognitions"
    — Joel Gould, DragonCode.cpp (onSendResults)

    In the Python compat layer, the sink calls us directly (no
    message posting), and resume is handled by the caller.

    Args:
        gram_handle: Grammar handle (id of ComGramObj)
        flags: ISRNOTEFIN flags
        res_obj: ComResObj wrapping the recognition result
    """
    with _state.lock:
        gram = _state.grammar_registry.get(gram_handle)

    if gram is None:
        log.debug("PhraseFinish for unknown grammar handle %d", gram_handle)
        return

    cb = getattr(gram, "_results_callback", None)
    if cb is None:
        return

    details = _classify_result(flags, res_obj, gram)
    if details is None:
        return  # not this grammar and allResults not set

    with _callback_trace("phrase_finish"):
        try:
            cb(details, ResObj(res_obj))
        except Exception:
            log.exception("Error in results callback")


def dispatch_phrase_hypothesis(gram_handle, words):
    """Fire the hypothesis callback. Called by GrammarSink.PhraseHypothesis."""
    with _state.lock:
        gram = _state.grammar_registry.get(gram_handle)

    if gram is None:
        return

    cb = getattr(gram, "_hypothesis_callback", None)
    if cb is None:
        return

    with _callback_trace("phrase_hypothesis"):
        try:
            cb(words)
        except Exception:
            log.exception("Error in hypothesis callback")


def dispatch_dict_text_changed(dict_handle, del_start, del_end, new_text,
                               sel_start, sel_end):
    """Fire dictation text change callback.

    Called for both TextChanged and TextSelChanged notifications.
    "When a recognition occurs we usually get either a TextChanged or a
    TextSelChanged callback.  Although because of a coding bug (?) we get
    both when a 'Scratch That' command occurs."
    — Joel Gould, DictationObject.cpp (CVDct0NotifySink)
    """
    with _state.lock:
        dobj = _state.dict_registry.get(dict_handle)

    if dobj is None:
        return

    cb = getattr(dobj, "_change_callback", None)
    if cb is None:
        return

    with _callback_trace("dict_text_changed"):
        try:
            cb(del_start, del_end, new_text, sel_start, sel_end)
        except Exception:
            log.exception("Error in dictation change callback")


def dispatch_dict_begin_callback(dict_handle, module_info):
    """Fire dictation begin callback (JIT pause).

    "We get this callback when recognition is about to start but before
    the voice dictation object has activated its grammars.  This allows
    us to make sure we are in sync with the internal buffer."
    — Joel Gould, DictationObject.cpp (CVDct0NotifySink::JITPause)
    """
    with _state.lock:
        dobj = _state.dict_registry.get(dict_handle)

    if dobj is None:
        return

    cb = getattr(dobj, "_begin_callback", None)
    if cb is None:
        return

    with _callback_trace("dict_begin"):
        try:
            cb(module_info)
        except Exception:
            log.exception("Error in dictation begin callback")


# --- Public callback registration API ---

def _get_owner(callback):
    """Determine the owner of a callback for dedup and removal.

    Bound methods → the instance (__self__).
    Plain functions → the module name string (__module__).
    Lambdas/closures → None (no owner, no dedup).
    """
    owner = getattr(callback, "__self__", None)
    if owner is not None:
        return owner
    # Plain function with a real module (not lambda)
    name = getattr(callback, "__name__", "")
    mod = getattr(callback, "__module__", None)
    if mod and name and name != "<lambda>":
        return mod
    return None


def _set_callback(cb_list, callback):
    """Add or remove a callback from a callback list.

    If callback is None, removes all entries (full clear).
    If a callback from the same owner is already registered,
    replaces it. Otherwise appends. Lambdas with no owner
    replace any existing ownerless entry to prevent accumulation.
    """
    if callback is None:
        cb_list.clear()
        return

    owner = _get_owner(callback)
    for i, existing in enumerate(cb_list):
        existing_owner = _get_owner(existing)
        if owner is not None and existing_owner == owner:
            cb_list[i] = callback
            return
        if owner is None and existing_owner is None:
            # Replace existing ownerless callback (prevents lambda accumulation)
            cb_list[i] = callback
            return
    cb_list.append(callback)


def _loader_package(obj):
    """Top-level package name for a loader or any object.

    Checks the _loaders registry first, falls back to __module__/__name__.
    """
    from ._loaders import _loader_base_name
    pkg = _loader_base_name(obj)
    if pkg:
        return pkg
    mod = getattr(obj, "__module__", None) or getattr(obj, "__name__", "") or ""
    return mod.split(".")[0]


def _remove_callbacks_for(loader):
    """Remove all callbacks registered by a loader or its helper objects.

    Matches by:
    - Bound method owner whose __module__ shares the loader's top-level package
    - Plain function whose __module__ shares the loader's top-level package
    """
    pkg = _loader_package(loader)
    if not pkg:
        return

    def _owned_by_loader(cb):
        owner = _get_owner(cb)
        if owner is loader:
            return True
        # Bound method on a helper object within the same package
        if owner is not None and not isinstance(owner, str):
            owner_pkg = _loader_package(owner)
            return owner_pkg == pkg
        # Plain function from the same package
        if isinstance(owner, str):
            return owner.split(".")[0] == pkg
        return False

    for cb_list in (_state.begin_callbacks, _state.change_callbacks,
                    _state.timer_callbacks):
        cb_list[:] = [cb for cb in cb_list if not _owned_by_loader(cb)]


def setBeginCallback(callback):
    """Register a callback invoked at the start of each recognition.

    Dragon pauses all recognition processing until the callback returns.
    It is safe to call other natlink functions from within the callback.

    The callback receives a single parameter: the same ``(module_path,
    window_title, window_handle)`` tuple returned by getCurrentModule.

    The global begin callback fires first, followed by per-grammar begin
    callbacks (set via ``GramObj.setBeginCallback``).

    Pass ``None`` to clear the callback.
    """
    _set_callback(_state.begin_callbacks, callback)


def setChangeCallback(callback):
    """Register a callback invoked when something in the system changes.

    The callback receives two parameters ``(change_type, info)``:

    - ``("user", (user_name, speech_dir))`` — active user changed
    - ``("mic", mic_state_string)`` — microphone state changed

    Pass ``None`` to clear the callback.
    """
    _set_callback(_state.change_callbacks, callback)


def setTimerCallback(pCallback: object, nMilliseconds: int = 50):
    """Register a callback that fires automatically every N milliseconds.

    The callback receives no parameters. Pass ``None`` to clear the timer.

    Args:
        pCallback: A callable or ``None`` to clear.
        nMilliseconds: Timer interval in milliseconds (default 50).
    """
    from ._helpers import com_call
    _set_callback(_state.timer_callbacks, pCallback)
    # Legacy natlink allowed registration before natConnect. Record the
    # callback unconditionally; only drive the COM timer when connected.
    if not _state.connected or _state.backend is None:
        log.debug("setTimerCallback recorded while disconnected; "
                  "COM timer not started")
        return
    com_call(
        "setTimerCallback",
        _state.backend.set_timer_callback,
        pCallback is not None,
        nMilliseconds if pCallback is not None else 0,
    )


# --- Engine event handlers (registered into DragonConnection slots) ---

def _on_attrib_changed(dwCode):
    """Handle Dragon attribute change events."""
    if _state.during_init:
        return

    if dwCode == ISRNSAC_SPEAKER:
        user, directory = "", ""
        try:
            user, directory = _state.backend.get_current_user()
        except Exception:
            log.debug("Could not get user for AttribChanged", exc_info=True)
        if user != _state.last_user_name or directory != _state.last_user_dir:
            _state.last_user_name = user
            _state.last_user_dir = directory
            from ._ui_protocol import notify_ui
            notify_ui()
            dispatch_change_callback("user", user, directory)

    elif dwCode == DGNSRAC_MICSTATE:
        mic = "error"
        try:
            mic = _state.backend.get_mic_state()
        except Exception:
            log.debug("Could not get mic state for AttribChanged", exc_info=True)
        log.getChild("change").info("mic state → %s", mic)
        if mic != _state.last_mic_state:
            _state.last_mic_state = mic
            from ._ui_protocol import notify_ui
            notify_ui()
            dispatch_change_callback("mic", mic)


def _on_paused():
    """Handle JIT pause: fire begin callbacks.

    Called from the engine sink via on_paused_dispatch callback slot.
    Resume is handled by the sink after this returns.

    "You must call Resume to get the engine started again.  Just returning
    from this function is not enough."
    — Joel Gould, DragonCode.cpp (doPausedProcessing)

    Order matches C++ doPausedProcessing:
      1. getCurrentModule (COM call — may re-enter via modal loop)
      2. m_bDuringPaused = TRUE
      3. begin callbacks
      4. m_bDuringPaused = FALSE
      5. Resume (in caller _do_paused_processing)

    The COM call MUST happen before setting during_paused.  In STA
    out-of-process, GetWindowModuleFileName enters a modal loop that
    can dispatch re-entrant Paused callbacks.  If during_paused were
    already True, the nested call's finally-clause would clear it,
    corrupting the outer call's state.
    """
    if _state.during_init:
        return

    t0 = time.perf_counter()

    # COM call first — before during_paused flag.
    # Note: this modal loop can dispatch a nested Paused callback,
    # causing recursion.  Stack depth is bounded by Dragon's pause
    # frequency (typically 1-2 levels; never observed > 2).
    module_info = _state.backend.get_current_module()
    t_module = time.perf_counter()

    _state.during_paused = True
    try:
        # C++ doPausedProcessing fires global begin + per-grammar begin.
        # Dictation begin is NOT fired here — it comes from the separate
        # DictSink.JITPause callback (CDictationObject::JITPause in C++).
        dispatch_begin_callback(module_info)

        with _state.lock:
            gram_handles = list(_state.grammar_registry)
        for handle in gram_handles:
            if handle not in _state.grammar_registry:
                continue
            dispatch_grammar_begin_callback(handle, module_info)
        t_end = time.perf_counter()

        total_ms = (t_end - t0) * 1000
        if total_ms > 30:
            log.warning("Paused dispatch: %.1fms total "
                        "(module=%.1f, %d grams=%.1f)",
                        total_ms,
                        (t_module - t0) * 1000,
                        len(gram_handles), (t_end - t_module) * 1000)
    finally:
        _state.during_paused = False
