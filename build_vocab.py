"""Build CLEAN vocabulary lists for prompt v2.1 from the catalog export, excluding the 40 gold records.
Each distinct term is checked once at id.loc.gov (main heading = text before the first '--') and sorted by what it resolves to:
    vocab_lcsh.txt   resolves in LCSH or LC names (LCNAF)      -> subjects_lcsh
    vocab_tgm.txt    resolves in TGM                           -> genre_tgm
    vocab_local.txt  resolves nowhere (local catalog headings) -> allowed in subjects_lcsh, but labelled LOCAL
Also writes vocab_classification.csv (every term, its source column, and how it was classified) for your error analysis.
A term from the LCTGM column that is really a name or place goes to the LCSH list, not the TGM list.
Run:  python3 build_vocab.py      (about 5-10 minutes the first time; results are cached)
"""
import csv, html, re
from idloc import status

def split_terms(text):
    """Un-escape HTML entities (e.g. &quot; &gt;) BEFORE splitting on ';', and collapse stray double spaces."""
    text = html.unescape(text or "")
    return [re.sub(r"\s+", " ", t).strip() for t in text.split(";") if t.strip()]

def clean_term(term):
    """Fix typing slips only (never names or '?d'): trim, drop leading punctuation, tidy ' -- ', fix two known case typos."""
    t = term.strip()
    t = re.sub(r"^[^\w]+", "", t)                  # leading punctuation such as an apostrophe
    t = re.sub(r"\s*--\s*", "--", t)               # 'Piers & wharves --Washington' -> 'Piers & wharves--Washington'
    t = t.replace("washington (State)", "Washington (State)").replace("SEattle", "Seattle")
    return re.sub(r"\s+", " ", t).strip()

def needs_review(term):
    """Unbalanced parentheses, or the place 'Washington (State)' repeated: a cataloger should fix these by hand."""
    return term.count("(") != term.count(")") or term.count("Washington (State)") > 1

gold = {r["id"] for r in csv.DictReader(open("manifest.csv", encoding="utf-8")) if r["in_gold_set"] == "Y"}
terms = {}   # cleaned term -> source column(s)
originals = {}   # cleaned term -> the form(s) as they appeared before cleaning
for r in csv.DictReader(open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE):
    if r["CONTENTdm number"] in gold: continue
    for col, key in (("LCSH", "Subjects (LCSH)"), ("LCTGM", "Subjects (LCTGM)")):
        for raw in split_terms(r[key]):
            t = clean_term(raw)
            if not t: continue
            terms.setdefault(t, set()).add(col)
            originals.setdefault(t, set()).add(raw)

def classify(term, cols):
    main = term.split("--")[0].strip()
    in_tgm = status(["tgm"], main)
    in_lc = status(["lcsh", "names"], main)
    if "LCTGM" in cols and "LCSH" not in cols:      # catalogers meant TGM: prefer it if it resolves there
        if in_tgm != "none": return "tgm", in_tgm
        if in_lc != "none": return "lcsh", in_lc
    else:                                            # catalogers meant LCSH
        if in_lc != "none": return "lcsh", in_lc
        if in_tgm != "none": return "tgm", in_tgm
    return "local", "none"

lists = {"lcsh": [], "tgm": [], "local": [], "review": []}; rows = []
for n, (t, cols) in enumerate(sorted(terms.items()), 1):
    cls, how = ("review", "not checked") if needs_review(t) else classify(t, cols)
    lists[cls].append(t)
    rows.append({"term": t, "original": " | ".join(sorted(originals[t])), "source_column": "+".join(sorted(cols)), "class": cls, "match": how})
    if n % 50 == 0: print(f"  checked {n}/{len(terms)}")
for cls, name in (("lcsh", "vocab_lcsh.txt"), ("tgm", "vocab_tgm.txt"), ("local", "vocab_local.txt"), ("review", "vocab_review.txt")):
    open(name, "w", encoding="utf-8").write("\n".join(sorted(set(lists[cls]))) + "\n")
    print(name, len(set(lists[cls])), "terms")
with open("vocab_classification.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["term", "original", "source_column", "class", "match"]); w.writeheader(); w.writerows(rows)
moved = sum(1 for r in rows if r["source_column"] == "LCTGM" and r["class"] != "tgm")
print(f"{moved} terms from the LCTGM column were moved out of the TGM list (names, places, or local headings)")
