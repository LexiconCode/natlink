# Logging

Audience: users and developers tuning natlink logging.

Purpose: document log file location, logging sections in `natlink.ini`, and the
available logger categories.

See also:

- [Configuration](index.md)
- [Settings](settings.md)
- [Troubleshooting](../troubleshooting.md)

## Log File

Default log file:

```text
%LOCALAPPDATA%\natlink\natlink.log
```

Override with `NATLINK_LOG_PATH`.

## Logging Section

```ini
[Logging]
ClientLevel = INFO
FileLevel = DEBUG
LogFile =
SlowCallbackMs = 200
```

## Per-Category Levels

```ini
[Logging.Levels]
natlink.callbacks = WARNING, DEBUG
natlink.com.grammar = DEBUG
```

Each category can use one level for both outputs or `client,file` for separate
message-window and file settings.

## Categories

| Category | Client | File | What it covers |
|----------|--------|------|---------------|
| `natlink` | WARNING | INFO | Root logger |
| `natlink.callbacks` | WARNING | DEBUG | COM sinks and callback dispatch |
| `natlink.com` | WARNING | INFO | COM bridge, speech ops, pump |
| `natlink.com.conn` | INFO | DEBUG | Connection lifecycle and TLB loading |
| `natlink.com.grammar` | WARNING | INFO | Grammar object operations |
| `natlink.com.dictation` | WARNING | INFO | Dictation object operations |
| `natlink.com.results` | WARNING | INFO | Result parsing |
| `natlink.com.marshal` | INFO | INFO | Marshal DLL registration |
| `natlink.com.lexicon` | WARNING | INFO | Vocabulary queries |
| `natlink.com.launcher` | INFO | INFO | Launcher lifecycle |
| `natlink.compat` | WARNING | INFO | Compatibility layer |
| `natlink.compat.tray` | WARNING | INFO | Tray icon and UI events |
