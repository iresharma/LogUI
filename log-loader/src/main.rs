//! Reads a JSON Lines log file and writes NDJSON to stdout: one line per log line,
//! each line is { "level", "message", "timestamp", "the_json", "raw" }.
//! Optional CLI: --level-key=K --message-key=K --timestamp-key=K. If omitted, keys are inferred.

use serde_json::{Map, Value};
use std::collections::HashMap;
use std::env;
use std::io::{self, BufRead, BufReader, Write};
use std::process::exit;
use std::{fs::File, path::Path};

const LEVEL_CANDIDATES: &[&str] = &["level", "log_level", "severity", "level_name", "lvl"];
const MESSAGE_CANDIDATES: &[&str] = &["message", "msg", "error", "error_message", "text", "summary", "body"];
const TIMESTAMP_CANDIDATES: &[&str] = &["timestamp", "time", "ts", "@timestamp", "created_at", "date", "datetime"];
const MESSAGE_TRUNCATE: usize = 50;

struct Config {
    path: String,
    level_key: Option<String>,
    message_key: Option<String>,
    timestamp_key: Option<String>,
}

fn parse_args(args: &[String]) -> Option<Config> {
    let mut path = None;
    let mut level_key = None;
    let mut message_key = None;
    let mut timestamp_key = None;
    for arg in args.iter().skip(1) {
        if arg.starts_with("--level-key=") {
            level_key = Some(arg.trim_start_matches("--level-key=").to_string());
        } else if arg.starts_with("--message-key=") {
            message_key = Some(arg.trim_start_matches("--message-key=").to_string());
        } else if arg.starts_with("--timestamp-key=") {
            timestamp_key = Some(arg.trim_start_matches("--timestamp-key=").to_string());
        } else if !arg.starts_with('-') {
            path = Some(arg.clone());
        }
    }
    Some(Config {
        path: path?,
        level_key,
        message_key,
        timestamp_key,
    })
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let config = match parse_args(&args) {
        Some(c) => c,
        None => {
            eprintln!("Usage: log-loader <path> [--level-key=K] [--message-key=K] [--timestamp-key=K]");
            exit(1);
        }
    };

    if let Err(e) = run(&config) {
        eprintln!("log-loader: {}", e);
        exit(1);
    }
}

fn run(config: &Config) -> io::Result<()> {
    let path = Path::new(&config.path);
    if !path.exists() {
        return Ok(());
    }

    let f = File::open(path)?;
    let reader = BufReader::new(f);
    let lines: Vec<String> = reader
        .lines()
        .filter_map(|l| l.ok())
        .map(|s| s.trim_end_matches(|c| c == '\n' || c == '\r').to_string())
        .collect();

    let parsed: Vec<(String, Value)> = lines
        .iter()
        .filter(|s| !s.trim().is_empty())
        .map(|s| {
            let trimmed = s.trim();
            (s.clone(), parse_line(trimmed))
        })
        .collect();

    let valid_entries: Vec<&Value> = parsed
        .iter()
        .filter(|(_, v)| !is_parse_error(v))
        .map(|(_, v)| v)
        .collect();

    let level_key = config
        .level_key
        .clone()
        .or_else(|| best_key(LEVEL_CANDIDATES, &valid_entries));
    let message_key = config
        .message_key
        .clone()
        .or_else(|| best_key(MESSAGE_CANDIDATES, &valid_entries));
    let timestamp_key = config
        .timestamp_key
        .clone()
        .or_else(|| best_key(TIMESTAMP_CANDIDATES, &valid_entries));

    let stdout = io::stdout();
    let mut out = stdout.lock();

    for (raw, entry) in &parsed {
        let (level, message, timestamp) = if is_parse_error(entry) {
            (String::new(), String::new(), String::new())
        } else {
            let obj = entry.as_object().unwrap();
            (
                extract_string(obj, level_key.as_deref(), 12),
                extract_message(obj, message_key.as_deref()),
                extract_string(obj, timestamp_key.as_deref(), 80),
            )
        };
        let row = serde_json::json!({
            "level": level,
            "message": message,
            "timestamp": timestamp,
            "the_json": entry,
            "raw": raw
        });
        serde_json::to_writer(&mut out, &row)?;
        out.write_all(b"\n")?;
    }
    out.flush()?;
    Ok(())
}

fn is_parse_error(v: &Value) -> bool {
    v.get("_parse_error").and_then(Value::as_bool).unwrap_or(false)
}

fn best_key(candidates: &[&str], valid: &[&Value]) -> Option<String> {
    let mut counts: HashMap<&str, u32> = HashMap::new();
    for key in candidates {
        counts.insert(*key, 0);
    }
    for obj in valid.iter().filter_map(|v| v.as_object()) {
        for key in candidates {
            if obj.contains_key(*key) {
                *counts.get_mut(key).unwrap() += 1;
            }
        }
    }
    candidates
        .iter()
        .filter(|k| counts.get(*k).copied().unwrap_or(0) > 0)
        .min_by_key(|k| {
            let c = counts.get(*k).copied().unwrap_or(0);
            (std::cmp::Reverse(c), *k)
        })
        .map(|s| (*s).to_string())
}

fn value_to_string(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        Value::String(s) => s.clone(),
        Value::Array(_) => "[array]".to_string(),
        Value::Object(_) => "[object]".to_string(),
    }
}

fn extract_string(obj: &Map<String, Value>, key: Option<&str>, max_len: usize) -> String {
    let key = match key {
        Some(k) if obj.contains_key(k) => k,
        _ => return String::new(),
    };
    let s = value_to_string(&obj[key]);
    let s = s.trim();
    if s.len() <= max_len {
        s.to_string()
    } else {
        format!("{}...", s[..max_len.saturating_sub(3)].trim_end())
    }
}

fn extract_message(obj: &Map<String, Value>, message_key: Option<&str>) -> String {
    let mut s = String::new();
    if let Some(k) = message_key {
        if obj.contains_key(k) {
            s = value_to_string(&obj[k]).trim().to_string();
        }
    }
    if s.is_empty() && obj.contains_key("error") {
        s = value_to_string(&obj["error"]).trim().to_string();
    }
    if s.len() > MESSAGE_TRUNCATE {
        s = format!("{}...", s[..MESSAGE_TRUNCATE.saturating_sub(3)].trim_end());
    }
    s
}

fn parse_line(line: &str) -> Value {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return Value::Object(Map::new());
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(Value::Object(map)) => Value::Object(map),
        Ok(_) => {
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
