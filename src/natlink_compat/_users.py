"""_users.py - Dragon user profile management functions."""

from typing import List, Optional

from ._helpers import _require_connected, com_call
from ._state import _state


def getAllUsers() -> List[str]:
    """Get a list of all Dragon user profiles."""
    _require_connected()
    return com_call("getAllUsers", _state.backend.get_all_users)


def createUser(userName: str, baseModel: str = "",
               baseTopic: str = "") -> None:
    """Create a new Dragon user profile."""
    _require_connected()
    com_call("createUser", _state.backend.create_user,
                userName, baseModel, baseTopic)


def openUser(userName: str) -> None:
    """Open/select a Dragon user profile."""
    _require_connected()
    com_call("openUser", _state.backend.select_user, userName)


def saveUser() -> None:
    """Save the current Dragon user profile."""
    _require_connected()
    com_call("saveUser", _state.backend.save_speaker)


def getUserTraining() -> Optional[str]:
    """Get user training status.

    Returns None if not calibrated, "calibrate" if calibrated but
    no batch training, or "trained" if batch training has been done.
    """
    _require_connected()
    result = com_call("getUserTraining", _state.backend.get_user_training)
    return result if result else None


# --- Training mode ---

def getTrainingMode():
    """Get the current training mode. Returns (modeString, speechLength) or None."""
    _require_connected()
    mode, speech_length = com_call("getTrainingMode", _state.backend.get_training_mode)
    if not mode:
        return None
    return (mode, speech_length)


def startTraining(mode: str) -> None:
    """Start a training session."""
    _require_connected()
    com_call("startTraining", _state.backend.start_training_mode, mode)


def finishTraining(bProcess: int = 1) -> None:
    """Finish training and optionally process the data."""
    _require_connected()
    com_call("finishTraining", _state.backend.finish_training, bool(bProcess))
