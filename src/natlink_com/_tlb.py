"""Type library loading with a natlink-owned comtypes cache.

Loads the version-appropriate dragon_interfaces TLB via comtypes.client.GetModule
and returns the generated wrapper module.

The TLB is version-specific:
  DNS 13-14: dragon_interfaces_v13_v14.tlb  (VDSITEINFOW, LANGUAGEW on W interfaces)
  DPI 15-16: dragon_interfaces_v15_v16.tlb  (VDSITEINFOA on W interfaces per dd10midl)

Use ``get_tlb()`` to get the cached module after ``load_tlb()`` has run.
"""

import logging
import os

log = logging.getLogger("natlink.com.conn")

# Module-level cache — set by load_tlb(), read by get_tlb().
_tlb_mod = None


def get_tlb():
    """Return the cached TLB module, loading it on first access."""
    if _tlb_mod is None:
        load_tlb()
    return _tlb_mod


def load_tlb(version_hint=None):
    """Load the Dragon type library and return the comtypes module.

    Selects the version-appropriate TLB based on detected Dragon version:
      DNS 13-14 → dragon_interfaces_v13_v14.tlb
      DPI 15-16 → dragon_interfaces_v15_v16.tlb

    Falls back to dragon_interfaces.tlb if version-specific TLB not found
    (backwards compat with pre-split builds).

    Stores generated wrappers in a per-user natlink cache directory
    derived from the TLB hash. A changed TLB automatically selects a new
    cache directory, so no explicit invalidation step is required.
    """
    global _tlb_mod
    import comtypes.client

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    tlb_path = _select_tlb(pkg_dir, version_hint)

    _configure_comtypes_cache(tlb_path)

    _tlb_mod = comtypes.client.GetModule(tlb_path)
    log.debug("Loaded TLB: %s (library=%s)",
              os.path.basename(tlb_path), _tlb_mod.__name__)
    return _tlb_mod


def _select_tlb(pkg_dir, version_hint=None):
    """Pick the version-appropriate TLB file.

    Priority:
      1. Explicit version_hint (13 or 15)
      2. Auto-detect from Dragon registry
      3. Fallback to dragon_interfaces.tlb
    """
    major = version_hint
    if major is None:
        try:
            from ._connection import _detect_dragon_major
            major = _detect_dragon_major()
        except Exception:
            major = 0

    if major and major <= 14:
        variant = "v13_v14"
    else:
        variant = "v15_v16"

    versioned = os.path.join(pkg_dir, f"dragon_interfaces_{variant}.tlb")
    if os.path.isfile(versioned):
        log.debug("Selected TLB variant: %s (Dragon %d)", variant, major or 0)
        return versioned

    # Fallback: legacy single TLB
    fallback = os.path.join(pkg_dir, "dragon_interfaces.tlb")
    if os.path.isfile(fallback):
        log.debug("Version-specific TLB not found; using dragon_interfaces.tlb")
        return fallback

    raise FileNotFoundError(
        f"No type library found: tried {variant} and fallback in {pkg_dir}")


def _configure_comtypes_cache(tlb_path):
    """Route comtypes codegen to a writable natlink-owned cache.

    If callers explicitly set ``comtypes.client.gen_dir = None`` we
    preserve in-memory generation (used by tests).
    """
    try:
        import hashlib
        import sys
        import tempfile
        import shutil
        import comtypes
        import comtypes.client
        import comtypes.gen

        if comtypes.client.gen_dir is None:
            log.debug("comtypes gen_dir=None; using in-memory codegen")
            return

        with open(tlb_path, "rb") as f:
            tlb_hash = hashlib.md5(f.read()).hexdigest()[:12]
        py_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
        comtypes_tag = f"ct{getattr(comtypes, '__version__', 'unknown')}"
        cache_tag = f"{py_tag}-{comtypes_tag}-{tlb_hash}"

        local_appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if not local_appdata:
            local_appdata = tempfile.gettempdir()
            log.debug("No LOCALAPPDATA/APPDATA; falling back to temp dir")

        cache_root = os.path.join(local_appdata, "natlink", "comtypes_gen")
        cache_dir = os.path.join(cache_root, cache_tag)
        os.makedirs(cache_dir, exist_ok=True)

        gen_path = list(comtypes.gen.__path__)
        gen_path = [p for p in gen_path if p != cache_dir]
        gen_path.insert(0, cache_dir)
        comtypes.gen.__path__ = gen_path

        comtypes.client.gen_dir = cache_dir
        log.debug("Using natlink comtypes cache: %s", cache_dir)

        # Best-effort cleanup of obsolete natlink cache directories.
        try:
            for entry in os.listdir(cache_root):
                path = os.path.join(cache_root, entry)
                if entry != cache_tag and os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
        except Exception:
            log.debug("Failed to prune old natlink comtypes caches", exc_info=True)
    except Exception:
        log.debug("Failed to configure natlink comtypes cache; using in-memory codegen", exc_info=True)
        try:
            import comtypes.client
            comtypes.client.gen_dir = None
        except Exception:
            pass
