//! Reads a JSON Lines log file and writes NDJSON to stdout: one line per log line,
//! each line is {"entry": <parsed object or error>, "raw": "<raw line>"}.
//! Exit code 0 on success, non-zero on I/O or invalid usage.

use serde_json::{Map, Value};
use std::env;
use std::io::{self, BufRead, BufReader, Write};
use std::process::exit;
use std::{fs::File, path::Path};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!("Usage: log_loader <path>");
        exit(1);
    }
    let path = &args[1];

    if let Err(e) = run(path) {
        eprintln!("log_loader: {}", e);
        exit(1);
    }
}

fn run(path: &str) -> io::Result<()> {
    let path = Path::new(path);
    if !path.exists() {
        return Ok(());
    }
    let f = File::open(path)?;
    let reader = BufReader::new(f);
    let stdout = io::stdout();
    let mut out = stdout.lock();

    for line in reader.lines() {
        let raw = line?;
        let trimmed = raw.trim_end_matches(|c| c == '\n' || c == '\r');
        if trimmed.trim().is_empty() {
            continue;
        }
        let entry = parse_line(trimmed);
        let row = serde_json::json!({ "entry": entry, "raw": trimmed });
        serde_json::to_writer(&mut out, &row)?;
        out.write_all(b"\n")?;
    }
    out.flush()?;
    Ok(())
}

fn parse_line(line: &str) -> Value {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return Value::Object(Map::new());
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(Value::Object(map)) => Value::Object(map),
        Ok(other) => {
            let mut err = Map::new();
            err.insert("_raw".into(), Value::String(trimmed.to_string()));
            err.insert("_parse_error".into(), Value::Bool(true));
            err.insert(
                "_message".into(),
                Value::String("top-level is not an object".into()),
            );
            Value::Object(err)
        }
        Err(_) => {
            let mut err = Map::new();
            err.insert("_raw".into(), Value::String(trimmed.to_string()));
            err.insert("_parse_error".into(), Value::Bool(true));
            Value::Object(err)
        }
    }
}
