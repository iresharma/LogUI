from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from pathlib import Path


_log = logging.getLogger(__name__)


def _load_rust_lib() -> ctypes.CDLL | None:
    """Best-effort loading of the Rust fuzzy library as a CDLL.

    Search order:
    1. RUST_FUZZY_LIB_PATH env var, if set.
    2. System library search via ctypes.util.find_library(\"rust_fuzzy\").
    3. Local build artifacts in ./rust_fuzzy/target/release.
    """
    env_path = os.environ.get("RUST_FUZZY_LIB_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            try:
                return ctypes.CDLL(str(p))
            except OSError:
                _log.debug("Failed to load rust_fuzzy from RUST_FUZZY_LIB_PATH=%s", env_path)

    # Try system/lib search
    name = ctypes.util.find_library("rust_fuzzy")
    if name:
        try:
            return ctypes.CDLL(name)
        except OSError:
            _log.debug("Failed to load rust_fuzzy via find_library(%s)", name)

    # Try local cargo build output
    root = Path(__file__).parent
    candidates = [
        root / "rust_fuzzy" / "target" / "release" / "librust_fuzzy.dylib",
        root / "rust_fuzzy" / "target" / "debug" / "librust_fuzzy.dylib",
    ]
    for p in candidates:
        if p.exists():
            try:
                return ctypes.CDLL(str(p))
            except OSError:
                _log.debug("Failed to load rust_fuzzy from %s", p)

    _log.debug(
        "Rust fuzzy library not found; falling back to simple substring matching. "
        "Set RUST_FUZZY_LIB_PATH to the built librust_fuzzy.* path to enable it."
    )
    return None


_RUST_LIB = _load_rust_lib()
_RUST_FUNC = None
if _RUST_LIB is not None:
    try:
        func = _RUST_LIB.fuzzy_match_score
        func.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        func.restype = ctypes.c_longlong
        _RUST_FUNC = func
    except AttributeError:
        _log.debug("fuzzy_match_score symbol not found in rust_fuzzy library")
        _RUST_FUNC = None


def fuzzy_score(pattern: str, candidate: str) -> int:
    """Return the fuzzy match score from the Rust extension, or -1 on no match/error.

    If the Rust extension is unavailable, this falls back to a simple
    case-insensitive substring check, returning 0 for a match and -1 otherwise.
    """
    pattern = (pattern or "").strip()
    candidate = candidate or ""
    if not pattern:
        return 0

    if _RUST_FUNC is not None:
        try:
            pattern_bytes = pattern.encode("utf-8")
            candidate_bytes = candidate.encode("utf-8")
            return int(_RUST_FUNC(pattern_bytes, candidate_bytes))
        except Exception:
            # On any error, fall back to best-effort substring behavior.
            pass

    lower = pattern.lower()
    text = candidate.lower()
    return 0 if lower in text else -1


def fuzzy_match(pattern: str, candidate: str, min_score: int = 0) -> bool:
    """Return True if `candidate` fuzzily matches `pattern` with at least `min_score`.

    An empty pattern matches everything. When using the Rust backend, any
    non-negative score >= min_score is considered a match.
    """
    score = fuzzy_score(pattern, candidate)
    if (pattern or "").strip() == "":
        return True
    return score >= max(min_score, 0)

