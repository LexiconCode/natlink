# Contributing

Audience: contributors and maintainers working on natlink itself.

Purpose: document the core development workflow for setting up the repo,
running tests, and building documentation.

See also:

- [Developer Debugging](developer-debugging.md)
- [Testing](testing.md)
- [Architecture](architecture.md)

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (package manager)
- Windows 10 or 11

## Development Setup

Create a virtual environment and install all dependencies:

```powershell
uv venv .venv --python 3.14
uv pip install -e .[dev] --python .venv\Scripts\python.exe

.venv\Scripts\activate
or
uv run natlink-ui --install-shortcuts
```

## Building the Package

Build sdist + wheel:

```powershell
uv build
```

Output goes to `dist/`.

## Building Documentation

Build and serve the docs (default):

```powershell
.\scripts\docs.ps1
```

Build only or serve only:

```powershell
.\scripts\docs.ps1 -Build
.\scripts\docs.ps1 -Serve
```

The rendered site is written to `site/`. The preview server binds to
`http://127.0.0.1:8001/`.

