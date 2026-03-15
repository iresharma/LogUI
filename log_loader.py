"""Load and parse JSON Lines log files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_log_file(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a .txt file and parse each line as JSON.

    Args:
        path: Path to the log file.

    Returns:
        Tuple of (list of parsed log entries as dicts, list of raw lines for copy).
        Entries with parse errors are included as {"_raw": line, "_parse_error": True}.
    """
    path = Path(path)
    entries: list[dict[str, Any]] = []
    raw_lines: list[str] = []

    if not path.exists():
        return entries, raw_lines

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
