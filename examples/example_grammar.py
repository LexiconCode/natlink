"""Example: load a grammar, handle recognition, use dynamic lists.

Demonstrates the full GramObj lifecycle:
  1. Compile a grammar spec to binary
  2. Load, activate, register callbacks
  3. Handle recognition results
  4. Use dynamic lists (appendList, emptyList)
  5. Unload on exit

Usage:
    python example_grammar.py

Requires Dragon to be running. Say "hello world" or "open <app>"
where <app> is one of the items in the dynamic list.
"""

import sys
import time
sys.coinit_flags = 2  # STA

import natlink
from natlink_com.grammar_compiler import compile_grammar


GRAMMAR_SPEC = """
<greeting> exported = hello world;
<launch>   exported = open {apps};
"""


class MyGrammar:
    """A grammar that handles two rules: a greeting and a launch command."""

    def __init__(self):
        self.gram = natlink.GramObj()
        self._active = False

    def load(self):
        binary = compile_grammar(GRAMMAR_SPEC)
        self.gram.load(binary)

        # Register callbacks
        self.gram.setBeginCallback(self.on_begin)
        self.gram.setResultsCallback(self.on_results)

        # Populate the {apps} dynamic list
        self.gram.emptyList("apps")
        for app in ["notepad", "calculator", "browser", "terminal"]:
            self.gram.appendList("apps", app)

        # Activate both rules for all windows (hwnd=0)
        self.gram.activate("greeting", 0)
        self.gram.activate("launch", 0)
        self._active = True
        print("Grammar loaded and activated.")
        print('Say "hello world" or "open notepad/calculator/browser/terminal"')

    def unload(self):
        if self._active:
            self.gram.unload()
            self._active = False
            print("Grammar unloaded.")

    def on_begin(self, module_info):
        """Called at the start of each utterance."""
        pass

    def on_results(self, words, results):
        """Called when a phrase is recognized."""
        if not isinstance(words, list):
            return

        print(f"Recognized: {' '.join(words)}")

        # Check which rule matched
        if words[0] == "hello":
            print("  -> Greeting detected!")
        elif words[0] == "open" and len(words) > 1:
            app = words[1]
            print(f"  -> Launch: {app}")

            # Update the list dynamically
            self.gram.appendList("apps", "new-app")
            print('  -> Added "new-app" to the list')


def main():
    grammar = MyGrammar()
    with natlink.natConnect():
        grammar.load()
        print("\nListening... Press Ctrl+C to exit.\n")
        try:
            natlink.waitForSpeech()
        except KeyboardInterrupt:
            pass
        grammar.unload()  # explicit cleanup before natDisconnect


if __name__ == "__main__":
    main()
