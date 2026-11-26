"""The term-level REVIEW FLAG rule, shared by confidence_v2.py and make_review_sheet.py (one rule, one place). NO API calls.
A subject term is flagged for review when
   - the model gave it 'low' confidence, or
   - its main heading (text before the first '--') is not authorized at id.loc.gov (not found, or only a spelling variant).
Headings in vocab_local.txt (local catalog headings with no LC authority record) are NOT flagged for that reason.
Lookups come from id_cache.json through idloc.py. If a heading is not in the cache and the lookup fails (for example no network),
the heading is reported as 'unchecked' and the term is flagged with the reason "not checked" (never a false 'not found').
Use:  from term_flags import term_flag ;  term_flag("lcsh", "Seattle (Wash.)", "high")  ->  (False, "", "authorized")
"""
import pathlib
import idloc

_local = set(l.strip() for l in open("vocab_local.txt", encoding="utf-8")) if pathlib.Path("vocab_local.txt").exists() else set()

def vocab_status(kind, term):
    """authorized | variant | local | none | unchecked   (kind is 'lcsh' for subjects_lcsh, 'tgm' for genre_tgm)"""
    if kind == "lcsh" and term in _local: return "local"
    main = term.split("--")[0]
    services = ["lcsh", "names"] if kind == "lcsh" else ["tgm"]
    st = idloc.status(services, main)
    if st == "none" and f"{services[0]}|{main}" not in idloc.cache:      # the lookup never got a real answer
        return "unchecked"
    return st

def term_flag(kind, term, confidence):
    """returns (flagged: bool, reasons: str, vocab_status: str)"""
    st = vocab_status(kind, term); reasons = []
    if confidence == "low": reasons.append("low confidence")
    if st == "none": reasons.append("heading not found at id.loc.gov")
    elif st == "variant": reasons.append("heading is a variant, not the authorized form")
    elif st == "unchecked": reasons.append("heading not checked (no network); check it yourself")
    return bool(reasons), "; ".join(reasons), st
