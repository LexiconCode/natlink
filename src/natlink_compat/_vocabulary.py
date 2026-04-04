"""_vocabulary.py - Dragon vocabulary/lexicon functions."""

from typing import List, Optional, Union

from ._helpers import _require_connected, com_call
from ._state import _state


def getWordInfo(word: str, flags: int = 0) -> Optional[int]:
    """Get word properties. Returns bit flags, or None if word not in vocab."""
    _require_connected()
    result = com_call("getWordInfo", _state.backend.get_word_info, word, flags)
    return result


def addWord(word: str, wordInfo: int = 1,
            pronList: Union[str, List[str]] = None) -> int:
    """Add a word to the vocabulary.

    Each pronunciation is sent as a separate AddWord request, matching
    the original natlink behavior of calling ILexPronounce::Add per pron.

    Returns 1 if the word was added, 0 if it already existed (no prons case).
    """
    _require_connected()
    if pronList is None:
        added = com_call("addWord", _state.backend.add_word, word, "", wordInfo)
        return 1 if added else 0
    elif isinstance(pronList, str):
        com_call("addWord", _state.backend.add_word, word, pronList, wordInfo)
    else:
        for pron in pronList:
            com_call("addWord", _state.backend.add_word, word, pron, wordInfo)
    return 1


def deleteWord(word: str) -> None:
    """Delete a word from the vocabulary."""
    _require_connected()
    com_call("deleteWord", _state.backend.delete_word, word)


def setWordInfo(word: str, wordInfo: int) -> None:
    """Set word properties."""
    _require_connected()
    com_call("setWordInfo", _state.backend.set_word_info, word, wordInfo)


def getWordProns(wordName: str) -> Optional[List[str]]:
    """Get pronunciations for a word.

    Returns a list of pronunciation strings or None.
    """
    _require_connected()
    prons = com_call("getWordProns", _state.backend.get_word_prons, wordName)
    return prons


def enumerateWords() -> List[str]:
    """Enumerate vocabulary words exposed by Dragon's Unicode lexicon."""
    _require_connected()
    return com_call("enumerateWords", _state.backend.enumerate_words)


def enumeratePrefixWords(prefix: str) -> List[str]:
    """Enumerate vocabulary words matching a prefix."""
    _require_connected()
    return com_call("enumeratePrefixWords",
                    _state.backend.enumerate_prefix_words, prefix)


def getWordFromPrefix(prefix: str, flags: int = 0, index: int = 0) -> str:
    """Get a single vocabulary word match for a prefix lookup."""
    _require_connected()
    return com_call("getWordFromPrefix",
                    _state.backend.get_word_from_prefix, prefix, flags, index)


def getWordFromPron(pronunciation: str, flags: int = 0, index: int = 0) -> str:
    """Get a single vocabulary word match for a pronunciation lookup."""
    _require_connected()
    return com_call("getWordFromPron",
                    _state.backend.get_word_from_pron,
                    pronunciation, flags, index)
