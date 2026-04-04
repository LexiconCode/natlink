# Project Structure

```
natlink/
+-- src/
|   +-- natlink/                    # Drop-in replacement package
|   |   +-- __init__.py             # Re-export + legacy active_loader interception
|   |
|   +-- natlink_compat/            # Compatibility layer (headless core)
|   |   +-- __init__.py            # Public API, single-provider registration, action functions
|   |   +-- _actions.py            # Action functions (dragon, loader, config, mic)
|   |   +-- _callbacks.py          # Global callback registration/dispatch
|   |   +-- _cli.py                # CLI interface (natlink start/stop/info)
|   |   +-- _dict_obj.py           # DictObj (wraps ComDictObj)
|   |   +-- _exceptions.py        # NatError and 12 subclasses, com_call helper
|   |   +-- _gram_obj.py          # GramObj (wraps ComGramObj)
|   |   +-- _res_obj.py           # ResObj (wraps ComResObj)
|   |   +-- _state.py             # Global connection state (single ui_provider slot)
|   |   +-- _loaders.py           # Loader management: add/remove/get_loaders
|   |   +-- _loader_protocol.py   # LoaderProtocol (runtime-checkable)
|   |   +-- _ui_protocol.py       # UIProvider protocol, NatlinkState dataclass
|   |   +-- _ui_dispatch.py       # notify_ui(), notify_text(), set_phase()
|   |   +-- _orchestrator.py      # Headless launcher (composable steps, pump loop)
|   |   +-- _playstring.py        # playString / playEvents helpers
|   |   +-- _speech.py            # Speech-related functions (mic, mimic, etc.)
|   |   +-- _users.py             # User management functions
|   |   +-- _vocabulary.py        # Vocabulary/word functions
|   |   +-- _system.py            # System info functions
|   |   +-- _monitor.py           # Dragon process monitor
|   |   +-- _helpers.py           # Shared helper utilities
|   |   +-- _lifecycle.py         # natConnect / natDisconnect / waitForSpeech
|   |   +-- _logging_setup.py    # Logging configuration (file + notify_text handler)
|   |   +-- _win32.py             # Shared Win32 DLL handles and constants
|   |   +-- _legacy.py            # Legacy API shims
|   |
|   +-- natlink_com/              # Direct COM backend
|   |   +-- __init__.py            # Exports NatlinkCOM, NatlinkCOMError, etc.
|   |   +-- _cli.py                # Thin redirect to natlink_compat._cli
|   |   +-- _config.py             # Configuration file management (natlink.ini)
|   |   +-- _launcher.py           # Low-level primitives (COM probing, event hooks, mutex)
|   |   +-- _com_bridge.py        # NatlinkCOM: high-level COM API
|   |   +-- _connection.py        # DragonConnection: COM lifecycle
|   |   +-- _marshaling.py        # Marshal DLL registration (per-process)
|   |   +-- _sendinput.py        # SendInput fallback for playString/playEvents
|   |   +-- _guids.py             # COM GUIDs and CLSIDs
|   |   +-- _errors.py            # NatlinkCOMError
|   |   +-- _gram_obj.py          # ComGramObj: grammar object
|   |   +-- _grammar_sink.py      # ISRGramNotifySinkW implementation
|   |   +-- _res_obj.py           # ComResObj: recognition result object
|   |   +-- _dict_obj.py          # ComDictObj: dictation object
|   |   +-- _dict_sink.py         # IDgnVDctNotifySinkW implementation
|   |   +-- _engine_sink.py       # IDgnSREngineNotifySinkW implementation
|   |   +-- _action_sink.py       # IDgnSSvcActionNotifySinkW implementation
|   |   +-- grammar_compiler.py   # SAPI 4 + Dragon grammar compiler
|   |   +-- _grammar_parser.py   # Lark-based parser for SAPI 4.0 grammar syntax
|   |   +-- _dragon.py              # Dragon start/stop/restart/status + profile save
|   |   +-- _pump.py                 # Win32 message pump, message_loop, timer
|   |   +-- _hidden_wnd.py          # Hidden COM window (WM_USER messages, stash map)
|   |   +-- _lexicon.py             # Vocabulary operations (ILexPronounceW, IDgnLexWordW)
|   |   +-- _speech_ops.py          # Sync speech operations (mimic, playString, execScript)
|   |   +-- _user_ops.py            # User/speaker management (select, create, training)
|   |   +-- _win32.py               # Win32 helpers (clipboard, cursor, screen, module info)
|   |   +-- _sdata.py               # SDATA struct helpers (build/parse COM data blobs)
|   |   +-- _com_helpers.py         # COM helper utilities (force_release, addref_raw, etc.)
|   |   +-- _tlb.py                 # Type library loader
|   |   +-- *.idl, *.tlb, *.dll     # Pre-built marshal DLLs and type libraries
|   |
|   +-- natlink_ui/               # Default UI (separate namespace, same package)
|       +-- __init__.py            # UIProvider + UI-owned install/uninstall entry points
|       +-- _window.py             # NatlinkWindow: unified Win32 window + UI thread
|       +-- _stream_redirect.py   # sys.stdout/stderr → notify_text
|       +-- _config.py            # natlink_ui.ini management
|       +-- _shortcuts.py         # Desktop/startup shortcut management
|       +-- _win32.py              # Win32 definitions (own copy — clean edge)
|       +-- icons/                 # Icon assets
|
+-- tests/                         # Test suite
+-- scripts/                       # Developer scripts
+-- examples/                      # Usage examples
+-- CMakeLists.txt                 # CMake build for marshal DLLs
+-- pyproject.toml                 # Package metadata and build config
+-- docs/                          # Documentation
```

## Dependency Direction

```
natlink → natlink_compat → natlink_com → Dragon COM
               ↑
          natlink_ui (optional, discovered via entry point)
```

`natlink_com` never imports from `natlink_compat` or `natlink_ui`.
`natlink_compat` never imports from `natlink_ui` except in
`_orchestrator.py` as an optional fallback when no `natlink.ui_provider`
entry point loads.

`natlink_ui` imports from `natlink_compat` for protocols, state types,
and action functions. It is the default implementation of the `UIProvider`
protocol — third parties replace it by registering their own
`natlink.ui_provider` entry point.

Only one UI provider is active at a time. External shells such as
Electron implement `UIProvider` and register instead of
the default tray UI.

For details on each package's design and responsibilities, see [Architecture](architecture.md).
