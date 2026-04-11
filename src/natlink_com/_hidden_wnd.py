"""Hidden window for COM callback dispatch — matches C++ m_hMsgWnd pattern.

Sink callbacks (PhraseFinish, Paused, MimicDone, etc.) arrive on the STA
main thread and call post() to queue a Windows message to this window,
then return immediately so the COM call returns quickly to Dragon.

When the pump calls DispatchMessage, the message reaches this window's
wndproc, which looks up the registered handler and runs it.

Complex payloads (ComResObj, cookies, error strings) that don't fit in
wparam/lparam are stored in a dict via stash_put() and retrieved by the
handler via stash_pop().  The integer key is passed as lparam.

— Joel Gould, DragonCode.cpp (hiddenWndProc, postMessage)
"""

import ctypes
import ctypes.wintypes as wt
import itertools as _itertools
import logging

log = logging.getLogger("natlink.com.pump")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_longlong
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, ctypes.c_uint,
                              wt.WPARAM, wt.LPARAM)

user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassExW.restype = wt.ATOM
user32.CreateWindowExW.restype = wt.HWND
user32.DestroyWindow.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


# --- Window messages (matching C++ WM_USER+345..352) ---
# "Here are the various windows messages we send ourself.  We give this
# window message some random value to avoid conflicts."
# — Joel Gould, DragonCode.cpp (line 227-228)
WM_USER = 0x0400

# Active (used via PostMessage):
WM_PLAYBACK         = WM_USER + 345  # "this is used to detect when playback is done"
WM_EXECUTION        = WM_USER + 346  # "Used to detect when script execution is done"
WM_ATTRIBCHANGED    = WM_USER + 347  # "For when we get the AttribChanged2 notify sink callback"
WM_PAUSED           = WM_USER + 348  # "For when we get a Paused notify sink callback"
WM_SENDRESULTS      = WM_USER + 349  # "For when we should send results callback"
WM_MIMICDONE        = WM_USER + 350  # "For when we get teh MimicDone notify sink callback" [sic]
# C++ defines WM_HIDEWINDOW (351) and WM_TRAYICON (352) — not used here.
# We repurpose those slots for Python-only messages:
WM_PHRASE_HYPO      = WM_USER + 351  # Python-only: hypothesis callback (C++ was WM_HIDEWINDOW)
WM_DICT_TEXTCHANGED = WM_USER + 352  # Python-only: dict text changed (C++ was WM_TRAYICON)
WM_DEFERRED_CALL    = WM_USER + 353  # Python-only: run a callable on the main thread

# --- Payload stash ---
_stash = {}
_stash_seq = _itertools.count(1)


def stash_put(data):
    """Store a payload, return integer key for lparam."""
    key = next(_stash_seq)
    _stash[key] = data
    return key


def stash_pop(key):
    """Retrieve and remove a stashed payload."""
    return _stash.pop(key, None)


# --- Handler registry ---
_handlers = {}


def register_handler(msg_id, handler):
    _handlers[msg_id] = handler


def unregister_all_handlers():
    _handlers.clear()


# --- Window ---
_CLASS_NAME = "natlink_com"
_class_registered = False
_wndproc_ref = None
_hwnd = None


# C++ hiddenWndProc (line 576): "Note when a posted message comes in,
# the Python interpreter should be unlocked so we first have to
# establish a thread state and lock the interpreter."
# — Joel Gould, DragonCode.cpp (line 572-574)
# In this Python port the GIL serves the same role as CLockPython.
def _wndproc(hwnd, msg, wparam, lparam):
    handler = _handlers.get(msg)
    if handler is not None:
        try:
            handler(wparam, lparam)
        except Exception:
            log.exception("Hidden wndproc error (msg=0x%04X)", msg)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def create():
    """Create hidden window on main thread. Returns HWND or None."""
    global _class_registered, _wndproc_ref, _hwnd

    hInstance = kernel32.GetModuleHandleW(None)

    # Win32 window APIs use handled SEH internally — faulthandler's
    # vectored exception handler reports these as fatal even though
    # Windows handles them.  Disable around both RegisterClassExW
    # and CreateWindowExW.
    import faulthandler as _fh
    _fh_was_enabled = _fh.is_enabled()
    if _fh_was_enabled:
        _fh.disable()

    try:
        if not _class_registered:
            _wndproc_ref = WNDPROC(_wndproc)
            cls = WNDCLASSEXW()
            cls.cbSize = ctypes.sizeof(cls)
            cls.lpfnWndProc = _wndproc_ref
            cls.hInstance = hInstance
            cls.lpszClassName = _CLASS_NAME
            atom = user32.RegisterClassExW(ctypes.byref(cls))
            if not atom:
                log.error("RegisterClassExW failed: %d", ctypes.get_last_error())
                return None
            _class_registered = True

        _hwnd = user32.CreateWindowExW(
            0, _CLASS_NAME, _CLASS_NAME, 0x80000000,  # WS_POPUP
            0, 0, 0, 0, None, None, hInstance, None)
    finally:
        if _fh_was_enabled:
            _fh.enable()

    if not _hwnd:
        log.error("CreateWindowExW failed: %d", ctypes.get_last_error())
        return None

    log.debug("Hidden COM window created: 0x%X", _hwnd)
    _register_builtin_handlers()
    return _hwnd


def hwnd():
    """Return the hidden window handle, or None if not created."""
    return _hwnd


def destroy():
    """Destroy hidden window."""
    global _hwnd
    if _hwnd:
        user32.DestroyWindow(_hwnd)
        log.debug("Hidden COM window destroyed")
        _hwnd = None
    _stash.clear()


def post(msg, wparam=0, lparam=0):
    """Post message to hidden window. Cleans stash on failure."""
    hwnd = _hwnd
    if hwnd and user32.PostMessageW(hwnd, msg, wparam, lparam):
        return True
    if lparam:
        _stash.pop(lparam, None)
    return False


# --- Deferred calls (cross-thread → main STA thread) ---

def _handle_deferred_call(_wparam, lparam):
    payload = stash_pop(lparam)
    if payload:
        fn, args = payload
        fn(*args)


def _register_builtin_handlers():
    """Register handlers that must survive disconnect/reconnect cycles.

    Called from create() each time the hidden window is (re-)created,
    after unregister_all_handlers() wiped the previous set.
    """
    register_handler(WM_DEFERRED_CALL, _handle_deferred_call)


def push_to_com(fn, *args):
    """Schedule fn(*args) to run on the COM (STA) thread.

    Posts WM_DEFERRED_CALL to the hidden window so the callable
    executes during DispatchMessage on the thread that owns COM.
    Safe to call from any thread.  Fire-and-forget — no return value.

    If the hidden window does not exist (no COM connection), the call
    is silently dropped — there is no COM to talk to anyway.
    """
    key = stash_put((fn, args))
    if not post(WM_DEFERRED_CALL, lparam=key):
        stash_pop(key)
        log.debug("push_to_com: dropped (no hidden window)")
