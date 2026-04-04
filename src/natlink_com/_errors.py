"""Error handling: HRESULT -> exception mapping."""

import logging

log = logging.getLogger("natlink.com")


class NatlinkCOMError(Exception):
    """COM operation error with .error_type, .hr, and .error_message.

    natlink_compat uses these attributes for exception mapping to
    the original natlink NatError hierarchy.
    """
    def __init__(self, operation: str, hr: int = 0,
                 error_type: int = 0, error_message: str = ""):
        self.error_type = error_type
        self.hr = hr
        self.error_message = error_message or f"HRESULT 0x{hr & 0xFFFFFFFF:08X}"
        super().__init__(f"{operation}: {self.error_message}")


def check_hresult(hr: int, operation: str) -> None:
    """Raise NatlinkCOMError if HRESULT indicates failure (hr < 0)."""
    if hr < 0:
        raise NatlinkCOMError(operation, hr=hr)
