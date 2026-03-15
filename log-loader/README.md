# log-loader (Rust)

Fast JSON Lines log file loader used by the LogUI TUI. Reads a file path from argv, parses each line as JSON, and writes NDJSON to stdout (`{"entry": <obj>, "raw": "<line>"}` per line). The Python app spawns this binary and parses stdout; if the binary is missing or fails, it falls back to pure Python.

## Build

Requires [Rust](https://rustup.rs). From this directory:

```bash
cargo build --release
```

Binary output: `target/release/log-loader` (or `log-loader.exe` on Windows). The Python `log_loader` module looks for it in:

- `log-loader/target/release/log-loader` (project root)
- Same directory as `log_loader.py`
- `PATH` (`log-loader`)
