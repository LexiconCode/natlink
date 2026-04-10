# API Guide

Audience: third-party integrators building on natlink.

Purpose: define the supported public contracts for custom UI providers, loaders,
and integration against natlink's runtime surface.

See also:

- [Architecture](../architecture.md) for internal system boundaries
- [Program Flow](../program_flow.md) for runtime sequencing
- [Project Structure](../structure.md) for code layout
- [Dragon API](api/dragon.md), [Loader API](api/loaders.md), and [UI API](api/ui.md)
  for exact signatures and docstrings

Start here if you are:

- embedding natlink into another tool
- replacing natlink's default UI
- shipping a loader via the `natlink.loaders` entry point group
- calling natlink's public Python API from your own package

There are two documentation entry points for third-party use:

- this page for integration contracts and supported seams
- the generated reference pages: [Dragon API](api/dragon.md),
  [Loader API](api/loaders.md), and [UI API](api/ui.md)

## Natlink Integration

The main supported extension seams are:

- loader discovery through `natlink.loaders` entry points
- runtime loader management through `add_loader()`, `remove_loader()`,
  `reload_loader()`, and `get_loaders()`
- connection lifecycle through `natConnect()` and `natDisconnect()`
- callbacks through `setBeginCallback()`, `setChangeCallback()`, and
  `setTimerCallback()`
- public speech, system, and user APIs exported from `natlink`

Prefer:

- documented names exported from `natlink`
- contracts documented on this page
- `LoaderProtocol` and entry-point-based discovery

Avoid:

- importing underscore-prefixed modules as hard dependencies
- relying on compatibility-only shims unless required for an existing framework
  integration
- coupling to `natlink_ui` implementation details

## UI Provider Contract

Implement `UIProvider` to receive state and text pushes from natlink:

```python
class MyUI:
    def on_state_changed(self, state):
        # state is a NatlinkState frozen dataclass
        ...

    def on_text(self, text, level=20):
        # level uses Python logging values: 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR
        ...

    def stop(self):
        # Clean up resources
        ...
```

Required methods:

- `on_state_changed(state: NatlinkState) -> None`
- `on_text(text: str, level: int = 20) -> None`
- `stop() -> None`

To issue commands back into natlink, import the module directly:

```python
import natlink_compat
natlink_compat.restart_dragon()
natlink_compat.set_log_level(10)
natlink_compat.reload_grammars()
```

Threading guarantee:

- natlink may call all methods from arbitrary threads
- implementations must be thread-safe

### Registration

Natlink supports one active provider at a time:

```python
import natlink_compat
natlink_compat.set_ui_provider(my_ui)
```

The active provider receives `NatlinkState` snapshots and text pushes.

### Discovery

UI providers are discovered via the ``natlink.ui_provider`` entry point group.
Register yours in ``pyproject.toml``:

```toml
[project.entry-points."natlink.ui_provider"]
my-ui = "my_package.ui:MyUIProvider"
```

Non-default entries take priority over natlink's built-in ``default`` entry.

### Electron / IPC Bridge Example

An Electron bridge is just another `UIProvider` that serializes over a pipe:

```python
class ElectronBridge:
    def on_state_changed(self, state):
        self.pipe.send_json({"type": "state", "data": asdict(state)})

    def on_text(self, text, level=20):
        self.pipe.send_json({"type": "text", "text": text, "level": level})

    def stop(self):
        self.pipe.close()
```

Commands from Electron arrive as JSON, the bridge calls `natlink_compat` functions:

```python
msg = self.pipe.recv_json()
if msg["action"] == "restart_dragon":
    natlink_compat.restart_dragon()
```

## Loader Contract

Preferred contract:

```python
def start():
    ...

def stop():
    ...
```

or an object implementing `start()` and `stop()`.

Lifecycle:

1. discovery/import
2. activation via `start()`

During discovery:

- natlink imports loader modules
- natlink calls optional module-level `setup()`

During activation:

- natlink calls `start()` after COM connection succeeds

During shutdown:

- natlink calls `stop()` before COM teardown

Compatibility-only shims still exist for natlinkcore-style loaders:

- module-level `run()`
- `trigger_load()`
- `unload_all_loaded_modules()`
- `natlink.active_loader`

New third-party loaders should not depend on those unless intentionally
targeting that compatibility contract.
