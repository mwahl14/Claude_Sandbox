"""Score AI output against the cataloger-created gold records.
Usage:  python3 score.py --prompt v2            (one run)
        python3 score.py --prompt v1 --prompt2 v2   (not needed; just run once per prompt)
Reads:   manifest.csv, Prosch_Export.txt, outputs/<prompt>_<model>/*.json, (optional) validation.csv
Writes:  outputs/<run>/scores.csv   per-record scores
         outputs/<run>/rubric.csv   sheet for YOU to fill in: 1-3 rubric for description/alt text, error category, reviewer time
         summary.csv                one row per run and subset (dev / holdout / all) - appended each time
SUBJECT MATCHING (partial credit, as agreed):
  exact   = same heading string after normalizing case, '&'/'and', trailing periods     -> credit 1.0
  partial = same MAIN heading (text before the first '--') but different subdivisions  -> credit 0.5
  none    = otherwise                                                                  -> credit 0.0
  Precision = credit earned by AI terms / number of AI terms.  Recall = credit earned by gold terms / number of gold terms.
  Strict versions count exact matches only.
CAVEATS: gold 'LCSH' and 'LCTGM' columns are mixed (local names in LCSH, name headings in LCTGM), so the headline subject
numbers are POOLED across both columns. Gold was created in 2000-2001; superseded headings count against the AI.
"""
import argparse, csv, difflib, html, json, pathlib, re

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v1")
ap.add_argument("--model", default="claude-sonnet-5-5")
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"

manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
catalog = {r["CONTENTdm number"]: r for r in csv.DictReader(
    open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}
validation = {}
if (run / "validation.csv").exists():
    validation = {r["id"]: r for r in csv.DictReader(open(run / "validation.csv", encoding="utf-8"))}

# ---------- subjects ----------
def norm(t):
    t = t.lower().replace("&", "and")
    t = re.sub(r"\s*--\s*", "--", t)      # 'X --Y' equals 'X--Y'
    t = re.sub(r"\s+", " ", t).strip().rstrip(".")
    return t
def main(t): return norm(t.split("--")[0])
def split_terms(s):
    """un-escape HTML entities (&quot; &gt;) before splitting on ';', and collapse stray spaces"""
    return [re.sub(r"\s+", " ", t).strip() for t in html.unescape(s or "").split(";") if t.strip()]

def credit(term, others):
    """best credit for one term against a list of terms: 1.0 exact, 0.5 same main heading, else 0"""
    n, m = norm(term), main(term)
    best = 0.0
    for o in others:
        if norm(o) == n: return 1.0
        if main(o) == m: best = 0.5
    return best

def pr(ai, gold):
    """returns (partial credit sum for AI, exact count for AI, n_ai, partial credit sum for gold, exact count for gold, n_gold)"""
    a = [credit(t, gold) for t in ai]; g = [credit(t, ai) for t in gold]
    return sum(a), sum(c == 1.0 for c in a), len(ai), sum(g), sum(c == 1.0 for c in g), len(gold)

# ---------- dates ----------
def years_from_gold(edtf):
    """gold Date-EDTF -> (lo, hi) or None.  Handles 1889, 1883-07-04, 1880/1889, 188u, 188X"""
    s = (edtf or "").strip()
    if not s: return None
    m = re.fullmatch(r"(\d{3})[uUxX]", s)
    if m: return int(m.group(1) + "0"), int(m.group(1) + "9")
    ys = [int(y) for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", s)]
    return (min(ys), max(ys)) if ys else None

def years_from_ai(text):
    """AI free-text date -> (lo, hi) or None.  '1889', '1880s', 'mid-1880s', '1880-1890', 'ca. 1875', 'late 19th century'"""
    s = (text or "").lower()
    ranges = []
    for m in re.finditer(r"(?<!\d)(\d{3})0s", s): ranges.append((int(m.group(1) + "0"), int(m.group(1) + "9")))
    for m in re.finditer(r"(?<!\d)(\d{2})00s", s): ranges.append((int(m.group(1) + "00"), int(m.group(1) + "99")))
    s2 = re.sub(r"(?<!\d)\d{3,4}0?s", " ", s)
    for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", s2): ranges.append((int(m.group(1)), int(m.group(1))))
    m = re.search(r"(early|mid|late)?[\s-]*(\d{2})(st|nd|rd|th) century", s)
    if m and not ranges:
        base = (int(m.group(2)) - 1) * 100
        span = {"early": (0, 33), "mid": (34, 66), "late": (67, 99), None: (0, 99)}[m.group(1)]
        ranges.append((base + span[0], base + span[1]))
    if not ranges: return None
    return min(r[0] for r in ranges), max(r[1] for r in ranges)

def date_grade(ai, gold):
    if not ai or not gold: return "unparsed"
    if gold[0] <= ai[0] and ai[1] <= gold[1]: return "correct"
    if ai[0] <= gold[1] and gold[0] <= ai[1]: return "partial"
    return "wrong"

# ---------- places ----------
def place_grade(ai_places, gold_loc):
    last = (gold_loc or "").split("--")[-1].strip().lower()
    if not ai_places: return "no place given"
    if last and any(last in p["place"].lower() for p in ai_places): return "correct"
    return "wrong"

# ---------- names ----------
def unsupported_names(people, cat):
    """AI claims a name came from visible text, but none of its capitalized words appear in the gold title/notes."""
    ref = (cat.get("Title", "") + " " + cat.get("Notes", "")).lower()
    bad = []
    for p in people:
        if p["name_source"] == "visible_text":
            caps = re.findall(r"\b[A-Z][a-z]{2,}\b", p["description"])
            if caps and not any(c.lower() in ref for c in caps): bad.append(p["description"])
    return bad

def words(s): return set(re.findall(r"[a-z]{3,}", (s or "").lower()))

# ---------- main loop ----------
rows, rubric = [], []
for p in sorted(run.glob("*.json")):
    rec = json.loads(p.read_text(encoding="utf-8")); i = rec["id"]
    m = manifest.get(i, {})
    if m.get("in_gold_set") != "Y": continue          # score gold records only
    cat = catalog[i]; subset = "holdout" if m.get("holdout") == "Y" else "dev"
    row = {"id": i, "subset": subset, "valid_json": "Y" if rec["valid"] else "N"}
    if rec["valid"]:
        o = rec["output"]
        g_lcsh, g_tgm = split_terms(cat["Subjects (LCSH)"]), split_terms(cat["Subjects (LCTGM)"])
        a_lcsh, a_tgm = [t["term"] for t in o["subjects_lcsh"]], [t["term"] for t in o["genre_tgm"]]
        for name, (a, g) in {"pooled": (a_lcsh + a_tgm, g_lcsh + g_tgm), "lcsh": (a_lcsh, g_lcsh), "tgm": (a_tgm, g_tgm)}.items():
            ap_, ae, na, gp, ge, ng = pr(a, g)
            row.update({f"{name}_ai_partial": ap_, f"{name}_ai_exact": ae, f"{name}_n_ai": na,
                        f"{name}_gold_partial": gp, f"{name}_gold_exact": ge, f"{name}_n_gold": ng})
        row["date_grade"] = date_grade(years_from_ai(o["date_estimate"]["value"]), years_from_gold(cat["Date-EDTF"]))
        row["place_grade"] = place_grade(o["depicted_places"], cat["Location Depicted"])
        un = unsupported_names(o["depicted_people"], cat)
        row["unsupported_names"] = len(un)
        row["names_flagged"] = "; ".join(un)
        d, a = words(o["description"]), words(o["alt_text"])
        row["desc_alt_overlap"] = round(len(d & a) / len(d | a), 2) if d | a else 0
        row["desc_words"] = len(o["description"].split())
        v = validation.get(i, {})
        row["lcsh_main_authorized"] = v.get("lcsh_main_authorized", ""); row["lcsh_terms_checked"] = v.get("lcsh_terms", "")
        row["tgm_authorized"] = v.get("tgm_authorized", ""); row["tgm_terms_checked"] = v.get("tgm_terms", "")
        row["confidence"] = v.get("confidence", ""); row["tier"] = v.get("tier", "")
        rubric.append({"id": i, "subset": subset, "ai_title": o["title_suggestion"], "gold_title": cat["Title"],
                       "ai_description": o["description"], "ai_alt_text": o["alt_text"],
                       "description_score_1to3": "", "alt_text_score_1to3": "", "reviewer_minutes": "",
                       "error_category": "", "error_notes": ""})
    else:
        rubric.append({"id": i, "subset": subset, "ai_title": "", "gold_title": cat["Title"], "ai_description": "(invalid output)",
                       "ai_alt_text": "", "description_score_1to3": "", "alt_text_score_1to3": "", "reviewer_minutes": "",
                       "error_category": "format failure", "error_notes": rec.get("error", "")})
    rows.append(row)

keys = []
for r in rows:
    for k in r:
        if k not in keys: keys.append(k)
with open(run / "scores.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
if rubric:
    with open(run / "rubric.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rubric[0])); w.writeheader(); w.writerows(rubric)

# ---------- summary ----------
def ssum(rs, k): return sum(float(r[k]) for r in rs if r.get(k) not in (None, ""))
def ratio(a, b): return round(a / b, 3) if b else ""
summ = []
for label, subset_rows in (("dev", [r for r in rows if r["subset"] == "dev"]),
                           ("holdout", [r for r in rows if r["subset"] == "holdout"]), ("all", rows)):
    ok = [r for r in subset_rows if r["valid_json"] == "Y"]
    if not subset_rows: continue
    s = {"run": run.name, "subset": label, "records": len(subset_rows), "valid_json_rate": ratio(len(ok), len(subset_rows))}
    for name in ("pooled", "lcsh", "tgm"):
        s[f"{name}_precision_partial"] = ratio(ssum(ok, f"{name}_ai_partial"), ssum(ok, f"{name}_n_ai"))
        s[f"{name}_recall_partial"] = ratio(ssum(ok, f"{name}_gold_partial"), ssum(ok, f"{name}_n_gold"))
        s[f"{name}_precision_strict"] = ratio(ssum(ok, f"{name}_ai_exact"), ssum(ok, f"{name}_n_ai"))
        s[f"{name}_recall_strict"] = ratio(ssum(ok, f"{name}_gold_exact"), ssum(ok, f"{name}_n_gold"))
    for g in ("correct", "partial", "wrong", "unparsed"):
        s[f"date_{g}"] = sum(r["date_grade"] == g for r in ok)
    for g in ("correct", "wrong", "no place given"):
        s[f"place_{g}"] = sum(r["place_grade"] == g for r in ok)
    s["records_with_unsupported_names"] = sum(1 for r in ok if r["unsupported_names"])
    s["mean_desc_alt_overlap"] = round(sum(r["desc_alt_overlap"] for r in ok) / len(ok), 3) if ok else ""
    s["lcsh_main_validity"] = ratio(ssum(ok, "lcsh_main_authorized"), ssum(ok, "lcsh_terms_checked"))
    s["tgm_validity"] = ratio(ssum(ok, "tgm_authorized"), ssum(ok, "tgm_terms_checked"))
    summ.append(s)
sp = pathlib.Path("summary.csv")
old = list(csv.DictReader(open(sp, encoding="utf-8"))) if sp.exists() else []
old = [r for r in old if r["run"] != run.name]          # replace this run's earlier rows
allrows = old + summ
fields = []
for r in allrows:
    for k in r:
        if k not in fields: fields.append(k)
with open(sp, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(allrows)
for s in summ:
    print(f"\n== {s['run']} / {s['subset']} ({s['records']} records, valid JSON {s['valid_json_rate']}) ==")
    print(f"subjects pooled  precision {s['pooled_precision_partial']} (strict {s['pooled_precision_strict']})   recall {s['pooled_recall_partial']} (strict {s['pooled_recall_strict']})")
    print(f"dates  correct {s['date_correct']}  partial {s['date_partial']}  wrong {s['date_wrong']}  unparsed {s['date_unparsed']}")
    print(f"places correct {s['place_correct']}  wrong {s['place_wrong']}  none {s['place_no place given']}")
    print(f"unsupported names {s['records_with_unsupported_names']}   description/alt overlap {s['mean_desc_alt_overlap']}")
print("\nwrote", run / "scores.csv", ",", run / "rubric.csv", ", summary.csv")
