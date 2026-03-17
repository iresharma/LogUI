from __future__ import annotations

import json
from pathlib import Path

from rust_fuzzy import fuzzy_match


def _sample_lines(path: Path, limit: int = 100) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        lines = []
        for i, line in enumerate(f):
            if i >= limit:
                break
            lines.append(line.rstrip("\n"))
        return lines


def main() -> None:
    root = Path(__file__).parent
    small = root / "example_logs_small.txt"
    large = root / "example_logs_large.txt"

    print(f"Using small log: {small}")
    print(f"Using large log: {large}")

    # Simple smoke tests: exact and slightly fuzzy queries.
    queries = [
        "error",
        "warning",
        "database",
        "databse",  # typo
    ]

    for path in (small, large):
        if not path.exists():
            print(f"Skipping {path} (missing)")
            continue
        lines = _sample_lines(path)
        print(f"\n=== File: {path} (first {len(lines)} lines) ===")
        for query in queries:
            matches = 0
            for raw in lines:
                try:
                    obj = json.loads(raw)
                except Exception:
                    obj = {"_raw": raw}
                candidate = f"{json.dumps(obj)}\n{raw}"
                if fuzzy_match(query, candidate):
                    matches += 1
            print(f"Query {query!r}: {matches} matches")


if __name__ == "__main__":
    main()

