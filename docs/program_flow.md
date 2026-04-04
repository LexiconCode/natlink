# Program Flow

Audience: natlink developers and maintainers.

Purpose: describe the operational sequence of launcher startup, COM connection,
callback dispatch, restart, and shutdown.

This document describes how natlink connects to Dragon, processes speech recognition events, restarts Dragon, and shuts down.

## Launcher Startup

When `natlink start` (or `python -m natlink_com._launcher`) runs:

1. **Acquire single-instance mutex** — prevents duplicate launchers.
2. **Phase 1 — Discover loaders**: calls `discover_loaders()` which imports loader modules via entry points and calls each module's optional `setup()` hook. Loaders may call `set_ui_provider()` at import time or in `setup()` to register a replacement provider early.
3. **Discover UI provider** — if no provider was registered yet, the orchestrator selects one `natlink.ui_provider` entry point, preferring non-`default` entries over the shipping `natlink_ui` provider. If entry point discovery finds nothing, it falls back to a direct `natlink_ui` import.
4. **Set phase `waiting_for_dragon`** — the active provider updates its UI to show the waiting state.
5. **Wait for Dragon window** — uses `SetWinEventHook(EVENT_OBJECT_CREATE)` for zero-polling detection of Dragon's `DgnBarMainWindowCls` window. Optionally auto-launches Dragon if configured.
6. **Set phase `connecting`** — probe COM readiness with `CoCreateInstance(DgnSite)` using exponential backoff (0.5s, 1s, 2s, 4s..., max 30s) until Dragon's COM server responds.
7. **Set phase `loading_profile`** — wait for Dragon's user profile to finish loading (detected via Dragon's log file).
8. **Phase 2 — Connect COM**: calls `_connect_com()` (see Connection Flow below).
9. **Phase 3 — Activate**: calls `_activate()` which sets phase to `connected`, starts loaders.
10. **Main loop** — uses `MsgWaitForMultipleObjects` to wait on two named events (`NatlinkShutdown` and `NatlinkRestartDragon`) plus Windows messages. Pumps messages, drains deferred callbacks, and handles Dragon monitor events (exit/reappear) on each iteration.

## Connection Flow

Connection happens in three phases, orchestrated by `natConnect()` (or called individually by the launcher).

### Phase 1: Discover Loaders — `discover_loaders()`

1. Imports loader modules discovered via `natlink.loaders` entry points.
2. Calls each module's optional `setup()` function. Loaders may call `set_ui_provider()` here to register a provider before the COM connection happens.
3. Returns a list of `(module, module_name)` tuples. Does **not** start loaders yet.

See [Natlink](third_party/index.md) for the public loader contract.

### Phase 2: UI Provider Discovery

If discovery did not register a provider, the orchestrator loads
`natlink.ui_provider` entry points and selects one provider. Non-`default`
entries take precedence over the shipping tray provider. If no entry point
loads successfully, natlink falls back to importing `natlink_ui.UIProvider`
directly.

### Phase 3: COM Connection — `_connect_com()`

Pure COM connection with no UI side effects:

1. **Acquire connection mutex** (`NatlinkConnectionActive`) — warns if another natlink process is already connected.
2. **Initialize deferred callback infrastructure** — creates the hidden message window used for cross-thread callback dispatch.
3. **Create backend** — instantiates `NatlinkCOM` (or uses an injected backend).
4. **`NatlinkCOM.connect()`** delegates to `DragonConnection.connect()`:
   - Detects Dragon version from registry (HKLM, WOW64 32-bit view)
   - Loads the version-specific type library (`dragon_interfaces.tlb`) via `comtypes.client.GetModule`
   - Registers the 64-bit marshal DLL (`marshal64_v13_v14.dll` or `marshal64_v15_v16.dll`) per-process via `LoadLibrary` + `DllGetClassObject` + `CoRegisterClassObject`, then `CoRegisterPSClsid` for each interface
   - Calls `CoCreateInstance(CLSID_DgnSite, CLSCTX_LOCAL_SERVER)` to get an `IUnknown` pointer to Dragon's site object
   - `QueryInterface` for `IServiceProvider`
   - `IServiceProvider::QueryService(DgnDictate, ISRCentralW)` to get the central speech recognition interface
   - `QueryService(SpchServices, IUnknown)` for the speech services object (output events, script interpreter)
   - **Core QI** on ISRCentralW: `IDgnSREngineControlW`, `ISRSpeakerW`, `IDgnSRLexiconW`, `IDgnLexWordW`, `IDgnSRAudioFileSourceW`; on SpchServices: `IDgnSSvcOutputEventW`, `IDgnSSvcInterpreterW`
   - Creates hidden COM message window (sinks post to it immediately on registration)
   - Registers engine notification sink (`IDgnSREngineNotifySinkW`) and action notification sink; wires `WM_ATTRIBCHANGED`, `WM_PAUSED`, `WM_MIMICDONE`, `WM_SENDRESULTS` message handlers
   - **Late QI**: `IDgnSRTrainingA` (after sinks, matching C++ order)
   - Gets Dragon version via `IDgnSREngineControlW::GetVersion()`
5. **Register callbacks** — connects the backend's sink events to natlink's callback dispatch system.

### Phase 4: Activation — `_activate()`

1. **Display startup diagnostics** in Dragon's Messages window (Python version, natlinkcore version).
2. **Set up logging** — rotating file handler + message window handler, redirect stdout/stderr through `displayText`.
3. **Register atexit handler** for clean disconnect on interpreter shutdown.
4. **Set phase `connected`** — the active provider receives a connected state snapshot.
5. **Start Dragon monitor thread** if not already running.
6. **Start loaders** — calls `start()` on each loader discovered in Phase 1.

## UI State Transitions

The launcher tracks its current phase via `set_phase()`. Providers decide how to render each phase; the default `natlink_ui` tray maps phases to icon color and tooltip text.

```
                          +-----------+
                          |   idle    |  (initial state)
                          +-----+-----+
                                |
                                v
                   +-------------------+
                   | waiting_for_dragon |  (tray: red/disconnected)
                   +--------+----------+
                            |
                            v
                      +------------+
                      | connecting |  (tray: yellow/connecting)
                      +-----+------+
                            |
                            v
                   +-----------------+
                   | loading_profile |  (tray: yellow/connecting)
                   +--------+--------+
                            |
                            v
                      +-----------+
              +------>| connected |  (tray: green/connected)
              |       +-----+-----+
              |             |
              |             | (Dragon exits or restart requested)
              |             v
              |      +------------+
              |      | restarting |  (tray: yellow/restarting)
              |      +-----+------+
              |            |
              |            v
              |  +-------------------+
              |  | waiting_for_dragon |
              |  +--------+----------+
              |           |
              |           v
              |     +------------+
              |     | connecting |
              |     +-----+------+
              |           |
              |           v
              |  +-----------------+
              |  | loading_profile |
              |  +--------+--------+
              |           |
              +----------+
              (reconnect succeeds)

              Any state ----> error  (tray: red/error with message)
```

## Dragon Restart

Natlink can restart Dragon without restarting itself (e.g., from the tray menu's "Restart Dragon" option).

### Signal Path

1. **`signal_restart()`** — called from a UI action or another controller thread. Opens the `NatlinkRestartDragon` named event and sets it.
2. **Main loop detects the event** — `MsgWaitForMultipleObjects` returns `WAIT_OBJECT_0 + 1`.
3. **`_do_restart_on_main(natlink)`** runs on the main thread (COM-safe, since the main thread owns COM objects).

### Restart Sequence

The restart runs entirely on the main thread:

1. **Set phase `restarting`** — the active provider receives the restart phase.
2. **Stop Dragon monitor** — prevents the monitor from interfering during restart.
3. **Save current profile** — calls `save_profile()` via Dragon's COM interface.
4. **Disconnect COM** — calls `natDisconnect()` to cleanly release all COM resources.
5. **`gc.collect()`** — ensures Python releases any lingering COM reference cycles before Dragon exits.
6. **Close Dragon gracefully** — sends `WM_CLOSE` to Dragon's windows. Waits up to 20 seconds for the process to exit. Falls back to force-kill if Dragon does not exit gracefully.
7. **Launch Dragon** — calls `dragon_start(wait=30)`.
8. **Set phase `waiting_for_dragon`** — wait for Dragon's main window to appear.
9. **Set phase `connecting`** — probe COM readiness with exponential backoff.
10. **Set phase `loading_profile`** — wait for the user profile to load (detected via Dragon's log file).
11. **Reconnect** — calls `natConnect()` which runs the full three-phase connection flow. On success, displays a restart confirmation message.
12. **On failure** — sets phase to `error` with the exception message.

## Speech Recognition Flow

### Utterance Begin

When Dragon starts processing an utterance:

1. Dragon calls the engine sink's `Paused` method with a cookie.
2. The engine sink posts `WM_PAUSED` to the hidden window. The handler calls `_do_paused`, which dispatches to `_on_paused()`:
   - Retrieves foreground module info via `get_current_module()` (COM call — may enter modal loop, must happen **before** setting `during_paused`)
   - Sets `during_paused = True`
   - Calls the user's begin callback with `(moduleInfo,)`
   - Sets `during_paused = False`
3. `ISRCentralW::Resume(cookie)` is called after `_on_paused` returns. `_resume_count` is incremented.

### Phrase Finish

When Dragon completes recognition of a phrase:

1. The grammar sink's `PhraseFinish` method is called with the recognition result data (`SRPHRASEW` structure).
2. The grammar sink creates a `ComResObj` wrapping the result.
3. The grammar sink calls `_on_results_callback(resObj)` which dispatches to the appropriate `GramObj.resultsCallback`.
4. The `GramObj` calls the user-registered `gotResultsObject`, `gotResults`, or `gotResultsInit` methods as appropriate.
5. After the callback returns, `ISRCentralW::Resume()` is called.

### Hypothesis

For grammar sinks registered with hypothesis notifications, Dragon calls `PhraseHypothesis` with partial results during recognition. This fires the user's `gotHypothesis` callback if registered.

## Sync Operations

All four sync operations (`recognitionMimic`, `playString`, `playEvents`,
`execScript`) use the same completion architecture, matching the original C++
`CDragonCode::messageLoop` pattern:

1. **Unique client code**: each call generates a unique client code. Dragon
   echoes it back in the completion callback (`MimicDone`, `PlaybackDone`,
   `ExecutionDone`).
2. **PostMessage**: completion callbacks post to the hidden window with the
   completion message and client code.
3. **TriggerMessage / message_loop**: `push_message_entry` registers the
   expected `(message, wParam)` pair. `message_loop` pumps messages and checks
   for the expected completion before and during normal dispatch, including the
   pre-consumed COM modal-loop case.
4. **Start callback**: the `start` callback drains pending messages before
   issuing the COM call, so stale paused/resume traffic from a previous cycle
   is handled first.

Several operations block the calling thread until Dragon signals completion:

### execScript

1. `exec_script()` validates the script via `IDgnSSvcInterpreterW::CheckScript`, then calls `ExecuteScript` (or `ExecuteScriptWithListResults` if args are provided).
2. The action sink's `ExecutionDone` posts `WM_EXECUTION` to the hidden window.
3. `_sync_op` pumps messages via `MsgWaitForMultipleObjects` + `PeekMessage` until triggered or timeout.

### recognitionMimic

1. `recognition_mimic()` pushes a `_MessageEntry(WM_MIMICDONE, clientCode)` onto the message stack.
2. `message_loop` drains pending messages (dispatching any leftover `WM_PAUSED → Resume` from a previous cycle), then calls `RecognitionMimic` via the `start` callback.
3. The engine sink's `MimicDone` posts `WM_MIMICDONE` to the hidden window with `wParam=clientCode`, `lParam=0` (success) or non-zero (failure).
4. `message_loop` pumps messages via `MsgWaitForMultipleObjects` + `PeekMessage` until the entry is triggered (matching on `WM_MIMICDONE` + `clientCode`).
5. If the first attempt fails and `_resume_count` increased (proving Dragon was paused from the audio-restart race), a retry is issued with a new client code. Genuine grammar mismatches propagate immediately.

See [Consecutive recognitionMimic](technical-limitations.md#consecutive-recognitionmimic-with-active-microphone) for the race condition details.

### playString / playEvents

1. `NatlinkCOM.play_string()` or `play_events()` calls `IDgnSSvcOutputEventW::PlayString` or `PlayEvents`.
2. DNS 16+ passes `dwNotify=1` as the final argument to request notification.
3. The action sink's `PlaybackDone` method is called by Dragon.
4. The calling thread waits on `_playback_done` event.
5. On legacy DLLs (DNS < 15), playback is fire-and-forget (no dwNotify support).

### inputFromFile

1. `_testFileName` validates the file exists and has a legal extension (`.utd`, `.utt`, `.utb`, `.wav`, `.nwv`). A re-entrancy guard prevents nested `inputFromFile` calls (Dragon supports only one active audio source).
2. `NatlinkCOM.input_from_file()` calls `IDgnSRAudioFileSourceW::LoadFile` then starts playback.
3. The engine sink's `AttribChanged2` posts `WM_ATTRIBCHANGED` with `DGNSRAC_PLAYBACKDONE`, which sets the `playback_done` Win32 event.
4. `pump()` waits on the event handle via `MsgWaitForMultipleObjects` until signaled or timeout (5 min).

## Shutdown

### Clean Exit via Shutdown Event

The launcher shuts down cleanly without `os._exit()`. The sequence:

1. **Signal** — an external process or UI action calls `request_shutdown()`, which opens and sets the `NatlinkShutdown` named event.
2. **Main loop exits** — `MsgWaitForMultipleObjects` returns `WAIT_OBJECT_0`, breaking out of the `while True` loop.
3. **Disconnect** — if still connected, calls `natDisconnect()` (see below).
4. **Stop UI** — calls `stop()` on the active provider if one is registered.
5. **Close event handles** — releases the shutdown and restart event handles.
6. **Process exits normally** — the main function returns, Python runs atexit handlers, and the process exits cleanly.

### natDisconnect Teardown

When `natDisconnect()` is called (either during shutdown or explicitly by user code):

1. **Stop Dragon monitor** — unless called from the monitor thread itself (auto-disconnect on Dragon exit needs the monitor to stay alive for reconnection).
2. **Stop all active loaders** — calls `stop()` on each.
3. **Set disconnect event** — unblocks `waitForSpeech` and posts `WM_APP` to wake any message loop.
4. **Cancel timer callback** if active.
5. **Unregister sinks** — calls `backend.unregister_sinks()` to stop Dragon from sending callbacks. This must happen before releasing COM interfaces to prevent deadlocks from in-flight RPC callbacks.
6. **Clear callback slots** — `_callbacks.unregister_all()`.
7. **Drain deferred callbacks** and shut down the deferred callback window.
8. **Remove logging handlers** — stops provider text dispatch from logging, restores stdout/stderr.
9. **Tear down objects** — unloads all grammar objects (`GramObj.unload()`), destroys dictation objects, destroys result objects.
10. **Disconnect backend** — calls `DragonConnection.disconnect()`:
    - Releases all COM interface references
    - Releases `IServiceProvider`
    - Revokes marshal DLL class registration and frees the DLL
11. **Set phase `idle`** — the active provider receives the disconnected state.
12. **Release connection mutex** — allows other natlink processes to connect without warning.
13. **Reset all connection state**.
