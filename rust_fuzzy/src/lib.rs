use fuzzy_matcher::skim::SkimMatcherV2;
use fuzzy_matcher::FuzzyMatcher;
use libc::c_char;
use std::ffi::{CStr};

/// C-ABI function: compute fuzzy match score between two UTF-8 strings.
///
/// - `pattern` and `candidate` are null-terminated UTF-8 C strings.
/// - Returns a non-negative score for a match, or -1 for no match/error.
#[no_mangle]
pub extern "C" fn fuzzy_match_score(pattern: *const c_char, candidate: *const c_char) -> i64 {
    if pattern.is_null() || candidate.is_null() {
        return -1;
    }

    let c_pattern = unsafe { CStr::from_ptr(pattern) };
    let c_candidate = unsafe { CStr::from_ptr(candidate) };

    let pattern_str = match c_pattern.to_str() {
        Ok(s) => s.trim(),
        Err(_) => return -1,
    };
    let candidate_str = match c_candidate.to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };

    if pattern_str.is_empty() {
        // Empty pattern conceptually matches everything with neutral score.
        return 0;
    }

    let matcher = SkimMatcherV2::default();
    let pattern_lc = pattern_str.to_lowercase();
    let candidate_lc = candidate_str.to_lowercase();

    matcher
        .fuzzy_match(&candidate_lc, &pattern_lc)
        .map(|s| s as i64)
        .unwrap_or(-1)
}
