"""Load and parse JSON Lines log files.

Uses a Rust binary (log_loader) when available for faster loading;
falls back to pure Python otherwise.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Set by load_log_file; read via load_used_rust() for UI/debug.
_used_rust: bool = False


def load_used_rust() -> bool:
    """Return True if the last load_log_file() call used the Rust binary."""
    return _used_rust


def _rust_binary_path() -> Path | None:
    """Path to the log-loader binary, or None if not found."""
    # Cargo uses package name: log-loader -> log-loader[.exe]
    name = "log-loader.exe" if sys.platform == "win32" else "log-loader"
    # Same directory as this module
    same_dir = Path(__file__).resolve().parent / name
    if same_dir.is_file():
        return same_dir
    # log-loader/target/release/log-loader (from project root)
    project_root = Path(__file__).resolve().parent
    release = project_root / "log-loader" / "target" / "release" / name
    if release.is_file():
        return release
    # PATH
    in_path = shutil.which("log-loader")
    if in_path:
        return Path(in_path)
    return None


def _load_via_rust(path: Path) -> tuple[list[dict[str, Any]], list[str]] | None:
    """Run Rust binary and parse NDJSON stdout. Returns None on any failure."""
    binary = _rust_binary_path()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [str(binary), str(path)],
            capture_output=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            return None
        stdout = result.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    entries: list[dict[str, Any]] = []
    raw_lines: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            entry = row.get("entry")
            raw = row.get("raw", "")
            if isinstance(entry, dict):
                entries.append(entry)
                raw_lines.append(raw if isinstance(raw, str) else str(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return entries, raw_lines


def _load_python(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Pure-Python implementation."""
    entries: list[dict[str, Any]] = []
    raw_lines: list[str] = []

    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.rstrip("\n\r")
            raw_lines.append(raw)
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    entries.append(obj)
                else:
                    entries.append({"_raw": raw, "_parse_error": True, "_message": "top-level is not an object"})
            except json.JSONDecodeError:
                entries.append({"_raw": raw, "_parse_error": True})

    return entries, raw_lines


def load_log_file(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a .txt file and parse each line as JSON.

    Uses the Rust log_loader binary when available for faster loading;
    otherwise falls back to pure Python.

    Args:
        path: Path to the log file.

    Returns:
        Tuple of (list of parsed log entries as dicts, list of raw lines for copy).
        Entries with parse errors are included as {"_raw": line, "_parse_error": True}.
    """
    global _used_rust
    path = Path(path)
    entries: list[dict[str, Any]] = []
    raw_lines: list[str] = []

    if not path.exists():
        _used_rust = False
        return entries, raw_lines

    rust_result = _load_via_rust(path)
    if rust_result is not None:
        _used_rust = True
        return rust_result
    _used_rust = False
    return _load_python(path)
