"""Load and parse JSON Lines log files.

Uses a Rust binary (log-loader) when available; returns rows with
level, message, timestamp, the_json, raw. Falls back to pure Python with same row shape.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from schema import infer_display_keys

# Set by load_log_file; read via load_used_rust() for UI/debug.
_used_rust: bool = False

MESSAGE_TRUNCATE = 50


def load_used_rust() -> bool:
    """Return True if the last load_log_file() call used the Rust binary."""
    return _used_rust


def _rust_binary_path() -> Path | None:
    """Path to the log-loader binary, or None if not found."""
    name = "log-loader.exe" if sys.platform == "win32" else "log-loader"
    same_dir = Path(__file__).resolve().parent / name
    if same_dir.is_file():
        return same_dir
    project_root = Path(__file__).resolve().parent
    release = project_root / "log-loader" / "target" / "release" / name
    if release.is_file():
        return release
    in_path = shutil.which("log-loader")
    if in_path:
        return Path(in_path)
    return None


def _load_via_rust(
    path: Path,
    level_key: str | None = None,
    message_key: str | None = None,
    timestamp_key: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """Run Rust binary and parse NDJSON stdout. Returns (rows, raw_lines) or None."""
    binary = _rust_binary_path()
    if not binary:
        return None
    argv = [str(binary), str(path)]
    if level_key:
        argv.append(f"--level-key={level_key}")
    if message_key:
        argv.append(f"--message-key={message_key}")
    if timestamp_key:
        argv.append(f"--timestamp-key={timestamp_key}")
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            return None
        stdout = result.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            if "the_json" not in row or "raw" not in row:
                continue
            rows.append(row)
        except (json.JSONDecodeError, TypeError):
            continue
    raw_lines = [r.get("raw", "") for r in rows]
    return rows, raw_lines


def _load_via_rust_stream(
    path: Path,
    level_key: str | None = None,
    message_key: str | None = None,
    timestamp_key: str | None = None,
    on_initial_batch: Callable[[list[dict[str, Any]], list[str]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """Run Rust binary in streaming mode and parse NDJSON stdout.

    Returns (rows, raw_lines) or None if the Rust binary is unavailable or fails.
    """
    binary = _rust_binary_path()
    if not binary:
        return None
    argv = [str(binary), str(path), "--stream"]
    if level_key:
        argv.append(f"--level-key={level_key}")
    if message_key:
        argv.append(f"--message-key={message_key}")
    if timestamp_key:
        argv.append(f"--timestamp-key={timestamp_key}")
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError:
        return None

    rows: list[dict[str, Any]] = []
    raw_lines: list[str] = []
    sent_initial = False

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        batch = obj.get("_batch")
        if batch == "tail_done":
            if on_initial_batch is not None and not sent_initial:
                # Make a shallow copy so the caller can't mutate our buffers.
                on_initial_batch(list(rows), list(raw_lines))
                sent_initial = True
            continue
        if batch == "done":
            break
        if "the_json" not in obj or "raw" not in obj:
            continue
        rows.append(obj)
        raw_lines.append(obj.get("raw", ""))

    try:
        proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        return None
    if proc.returncode not in (0, None) and not rows:
        return None
    return rows, raw_lines


def _format_value(val: Any, max_len: int) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return "[object]" if isinstance(val, dict) else "[array]"
    s = str(val).strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3].rstrip() + "..."


def _load_python(
    path: Path,
    level_key: str | None = None,
    message_key: str | None = None,
    timestamp_key: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pure-Python implementation returning same row shape as Rust."""
    entries: list[dict[str, Any]] = []
    raw_lines: list[str] = []

    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.rstrip("\n\r")
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    entries.append(obj)
                else:
                    entries.append({
                        "_raw": raw,
                        "_parse_error": True,
                        "_message": "top-level is not an object",
                    })
            except json.JSONDecodeError:
                entries.append({"_raw": raw, "_parse_error": True})
            raw_lines.append(raw)

    if not entries:
        return [], []

    if level_key is None or message_key is None or timestamp_key is None:
        inferred_level, inferred_msg, inferred_ts = infer_display_keys(entries)
        level_key = level_key or inferred_level
        message_key = message_key or inferred_msg
        timestamp_key = timestamp_key or inferred_ts

    rows: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        raw = raw_lines[i] if i < len(raw_lines) else ""
        if entry.get("_parse_error"):
            rows.append({
                "level": "",
                "message": "",
                "timestamp": "",
                "the_json": entry,
                "raw": raw,
            })
            continue
        level_val = _format_value(entry.get(level_key), 12) if level_key else ""
        msg_val = ""
        if message_key and message_key in entry:
            msg_val = _format_value(entry[message_key], MESSAGE_TRUNCATE)
        if not msg_val and "error" in entry:
            msg_val = _format_value(entry["error"], MESSAGE_TRUNCATE)
        ts_val = _format_value(entry.get(timestamp_key), 80) if timestamp_key else ""
        rows.append({
            "level": level_val,
            "message": msg_val,
            "timestamp": ts_val,
            "the_json": entry,
            "raw": raw,
        })
    return rows, raw_lines


def load_log_file(
    path: str | Path,
    level_key: str | None = None,
    message_key: str | None = None,
    timestamp_key: str | None = None,
    on_initial_batch: Callable[[list[dict[str, Any]], list[str]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a log file and return normalized rows.

    Each row has: level, message, timestamp, the_json, raw.
    Uses Rust binary when available; optional key overrides are passed to Rust.

    Returns:
        (rows, raw_lines) where raw_lines = [r["raw"] for r in rows].
    """
    global _used_rust
    path = Path(path)
    if not path.exists():
        _used_rust = False
        return [], []

    # If a callback is provided, prefer streaming mode so the UI can paint
    # after the tail batch is ready.
    if on_initial_batch is not None:
        rust_stream_result = _load_via_rust_stream(
            path,
            level_key=level_key,
            message_key=message_key,
            timestamp_key=timestamp_key,
            on_initial_batch=on_initial_batch,
        )
        if rust_stream_result is not None:
            _used_rust = True
            return rust_stream_result

    rust_result = _load_via_rust(path, level_key, message_key, timestamp_key)
    if rust_result is not None:
        _used_rust = True
        return rust_result
    _used_rust = False
    return _load_python(path, level_key, message_key, timestamp_key)
