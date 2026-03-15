//! Reads a JSON Lines log file and writes NDJSON to stdout: one line per log line,
//! each line is { "level", "message", "timestamp", "the_json", "raw" }.
//! Optional CLI: --level-key=K --message-key=K --timestamp-key=K. If omitted, keys are inferred.

use serde_json::{Map, Value};
use std::env;
use std::io::{self, Write, BufWriter};
use std::process::exit;
use std::{fs, path::Path};

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
        if let Some(v) = arg.strip_prefix("--level-key=") {
            level_key = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("--message-key=") {
            message_key = Some(v.to_string());
        } else if let Some(v) = arg.strip_prefix("--timestamp-key=") {
            timestamp_key = Some(v.to_string());
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

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

/// A parsed line holding a borrowed reference to the raw text and the parsed JSON.
struct Parsed<'a> {
    raw: &'a str,
    entry: Value,
}

fn run(config: &Config) -> io::Result<()> {
    let path = Path::new(&config.path);
    if !path.exists() {
        return Ok(());
    }

    // ── Read the entire file in one syscall ──────────────────────────────
    let content = fs::read_to_string(path)?;

    // ── Collect line slices (zero allocation per line) ───────────────────
    // We reference directly into `content`.
    let line_refs: Vec<&str> = content
        .split('\n')
        .map(|l| l.strip_suffix('\r').unwrap_or(l))
        .collect();

    // ── Single pass: parse + count key candidates ───────────────────────
    // Use fixed-size arrays instead of HashMap for cache-friendly counting.
    let mut level_counts  = [0u32; 5];  // matches LEVEL_CANDIDATES.len()
    let mut msg_counts    = [0u32; 7];  // matches MESSAGE_CANDIDATES.len()
    let mut ts_counts     = [0u32; 7];  // matches TIMESTAMP_CANDIDATES.len()

    let mut parsed: Vec<Parsed> = Vec::with_capacity(line_refs.len());

    for &raw in &line_refs {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            continue;
        }
        let entry = parse_line(trimmed);

        if let Some(obj) = entry.as_object() {
            if !obj.contains_key("_parse_error") {
                for (i, &k) in LEVEL_CANDIDATES.iter().enumerate() {
                    if obj.contains_key(k) { level_counts[i] += 1; }
                }
                for (i, &k) in MESSAGE_CANDIDATES.iter().enumerate() {
                    if obj.contains_key(k) { msg_counts[i] += 1; }
                }
                for (i, &k) in TIMESTAMP_CANDIDATES.iter().enumerate() {
                    if obj.contains_key(k) { ts_counts[i] += 1; }
                }
            }
        }

        parsed.push(Parsed { raw, entry });
    }

    // ── Infer keys ──────────────────────────────────────────────────────
    let level_key = config.level_key.clone()
        .or_else(|| pick_best(LEVEL_CANDIDATES, &level_counts));
    let message_key = config.message_key.clone()
        .or_else(|| pick_best(MESSAGE_CANDIDATES, &msg_counts));
    let timestamp_key = config.timestamp_key.clone()
        .or_else(|| pick_best(TIMESTAMP_CANDIDATES, &ts_counts));

    let lk = level_key.as_deref();
    let mk = message_key.as_deref();
    let tk = timestamp_key.as_deref();

    // ── Output ──────────────────────────────────────────────────────────
    let stdout = io::stdout();
    let mut out = BufWriter::with_capacity(256 * 1024, stdout.lock());

    // Reusable scratch buffers — never freed, just cleared each iteration.
    let mut level_buf = String::with_capacity(64);
    let mut msg_buf   = String::with_capacity(256);
    let mut ts_buf    = String::with_capacity(128);
    // Line buffer: we build the full JSON row here, then flush once.
    let mut row_buf: Vec<u8> = Vec::with_capacity(8192);

    for pl in &parsed {
        let is_err = is_parse_error(&pl.entry);

        if is_err {
            level_buf.clear();
            msg_buf.clear();
            ts_buf.clear();
        } else {
            let obj = pl.entry.as_object().unwrap();
            extract_string_into(&mut level_buf, obj, lk, 12);
            extract_message_into(&mut msg_buf, obj, mk);
            extract_string_into(&mut ts_buf, obj, tk, 80);
        }

        // Build the entire row in `row_buf`, then do a single write_all.
        row_buf.clear();
        row_buf.extend_from_slice(b"{\"level\":");
        write_json_str(&mut row_buf, &level_buf);
        row_buf.extend_from_slice(b",\"message\":");
        write_json_str(&mut row_buf, &msg_buf);
        row_buf.extend_from_slice(b",\"timestamp\":");
        write_json_str(&mut row_buf, &ts_buf);
        row_buf.extend_from_slice(b",\"the_json\":");
        // serde_json::to_writer into Vec<u8> is just a memcpy – no syscalls.
        serde_json::to_writer(&mut row_buf, &pl.entry)
            .map_err(|e| io::Error::new(io::ErrorKind::Other, e))?;
        row_buf.extend_from_slice(b",\"raw\":");
        write_json_str(&mut row_buf, pl.raw);
        row_buf.push(b'}');
        row_buf.push(b'\n');

        out.write_all(&row_buf)?;
    }
    out.flush()?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Fast JSON string escaping (replaces serde_json::to_writer for &str)
// ---------------------------------------------------------------------------

/// Write a JSON-encoded string (with quotes) into `buf`.
/// Fast path: scan for bytes that need escaping; memcpy everything in between.
#[inline]
fn write_json_str(buf: &mut Vec<u8>, s: &str) {
    buf.push(b'"');
    let bytes = s.as_bytes();
    let mut start = 0;
    let mut i = 0;
    while i < bytes.len() {
        let b = bytes[i];
        // Check if this byte needs escaping.
        let esc: &[u8] = match b {
            b'"'  => b"\\\"",
            b'\\' => b"\\\\",
            b'\n' => b"\\n",
            b'\r' => b"\\r",
            b'\t' => b"\\t",
            0x08  => b"\\b",
            0x0C  => b"\\f",
            0x00..=0x1F => {
                // Flush unescaped segment.
                buf.extend_from_slice(&bytes[start..i]);
                // \u00XX escape for other control chars.
                let hi = HEX_TABLE[(b >> 4) as usize];
                let lo = HEX_TABLE[(b & 0x0F) as usize];
                buf.extend_from_slice(&[b'\\', b'u', b'0', b'0', hi, lo]);
                i += 1;
                start = i;
                continue;
            }
            _ => {
                i += 1;
                continue;
            }
        };
        // Flush the clean segment before this byte, then write escape.
        buf.extend_from_slice(&bytes[start..i]);
        buf.extend_from_slice(esc);
        i += 1;
        start = i;
    }
    // Flush remaining clean segment.
    buf.extend_from_slice(&bytes[start..]);
    buf.push(b'"');
}

const HEX_TABLE: &[u8; 16] = b"0123456789abcdef";

// ---------------------------------------------------------------------------
// Key inference
// ---------------------------------------------------------------------------

fn pick_best(candidates: &[&str], counts: &[u32]) -> Option<String> {
    candidates
        .iter()
        .enumerate()
        .filter(|&(i, _)| counts[i] > 0)
        .min_by_key(|&(i, k)| (std::cmp::Reverse(counts[i]), *k))
        .map(|(_, s)| (*s).to_string())
}

// ---------------------------------------------------------------------------
// Field extraction (reuses caller-owned String buffers)
// ---------------------------------------------------------------------------

#[inline]
fn is_parse_error(v: &Value) -> bool {
    v.get("_parse_error").and_then(Value::as_bool).unwrap_or(false)
}

fn extract_string_into(
    buf: &mut String,
    obj: &Map<String, Value>,
    key: Option<&str>,
    max_len: usize,
) {
    buf.clear();
    let key = match key {
        Some(k) if obj.contains_key(k) => k,
        _ => return,
    };
    append_value_str(buf, &obj[key]);
    trim_in_place(buf);
    truncate_with_ellipsis(buf, max_len);
}

fn extract_message_into(
    buf: &mut String,
    obj: &Map<String, Value>,
    message_key: Option<&str>,
) {
    buf.clear();
    if let Some(k) = message_key {
        if let Some(v) = obj.get(k) {
            append_value_str(buf, v);
            trim_in_place(buf);
        }
    }
    if buf.is_empty() {
        if let Some(v) = obj.get("error") {
            append_value_str(buf, v);
            trim_in_place(buf);
        }
    }
    truncate_with_ellipsis(buf, MESSAGE_TRUNCATE);
}

/// Append JSON value as display string into `buf` without allocating.
#[inline]
fn append_value_str(buf: &mut String, v: &Value) {
    match v {
        Value::Null => {}
        Value::Bool(true)  => buf.push_str("true"),
        Value::Bool(false) => buf.push_str("false"),
        Value::Number(n) => {
            use std::fmt::Write;
            let _ = write!(buf, "{}", n);
        }
        Value::String(s) => buf.push_str(s),
        Value::Array(_)  => buf.push_str("[array]"),
        Value::Object(_) => buf.push_str("[object]"),
    }
}

/// Trim leading + trailing whitespace in-place without reallocating.
#[inline]
fn trim_in_place(buf: &mut String) {
    let lead = buf.len() - buf.trim_start().len();
    if lead > 0 {
        buf.drain(..lead);
    }
    let trail = buf.trim_end().len();
    buf.truncate(trail);
}

/// If `buf` exceeds `max`, truncate to `max-3` (char-safe) and append "...".
#[inline]
fn truncate_with_ellipsis(buf: &mut String, max: usize) {
    if buf.len() <= max {
        return;
    }
    let target = max.saturating_sub(3);
    let end = floor_char_boundary(buf, target);
    buf.truncate(end);
    // Trim any trailing whitespace from the truncated part.
    let t = buf.trim_end().len();
    buf.truncate(t);
    buf.push_str("...");
}

/// Largest byte index ≤ `i` that is a valid UTF-8 char boundary.
#[inline]
fn floor_char_boundary(s: &str, i: usize) -> usize {
    if i >= s.len() {
        return s.len();
    }
    let b = s.as_bytes();
    let mut pos = i;
    while pos > 0 && (b[pos] & 0xC0) == 0x80 {
        pos -= 1;
    }
    pos
}

// ---------------------------------------------------------------------------
// JSON line parser
// ---------------------------------------------------------------------------

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