"""Offline analysis of 'format' terms such as "Photograph albums" in a run's output. NO API calls, does not change any file.
Usage:  python3 analyze_format_terms.py --prompt v2.1
Reports:
  a) how many records (all 130, and the 30 dev gold records) have "Photograph albums" in genre_tgm
  b) the 15 most frequent genre_tgm and subjects_lcsh terms across all 130 records (AI terms only)
  c) pooled partial-credit precision / recall on the 30 DEV gold records, now and with "Photograph albums" removed
  d) other terms in vocab_tgm.txt that may describe the album page, mount or physical object (listed only, nothing removed)
The 10 holdout gold records are never read: part (c) uses dev records only (manifest holdout = N).
The helper functions (norm, main, split_terms, credit, pr) are copied from score.py so score.py is not changed.
"""
import argparse, collections, csv, html, json, pathlib, re

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v2.1")
ap.add_argument("--model", default="claude-sonnet-5-5")
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
TARGET = "photograph albums"

# ---- helpers copied from score.py ----
def norm(t):
    t = t.lower().replace("&", "and")
    t = re.sub(r"\s*--\s*", "--", t)
    t = re.sub(r"\s+", " ", t).strip().rstrip(".")
    return t
def main(t): return norm(t.split("--")[0])
def split_terms(s):
    return [re.sub(r"\s+", " ", t).strip() for t in html.unescape(s or "").split(";") if t.strip()]
def credit(term, others):
    n, m = norm(term), main(term)
    best = 0.0
    for o in others:
        if norm(o) == n: return 1.0
        if main(o) == m: best = 0.5
    return best
# ---------------------------------------

manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
dev_gold = {i for i, r in manifest.items() if r["in_gold_set"] == "Y" and r["holdout"] != "Y"}
catalog = {r["CONTENTdm number"]: r for r in csv.DictReader(
    open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}

recs = {}
for p in sorted(run.glob("[0-9]*.json")):
    r = json.loads(p.read_text(encoding="utf-8"))
    if r["valid"]: recs[r["id"]] = r["output"]

def is_target(t): return main(t) == TARGET

# ---- a) ----
print(f"== a) records with 'Photograph albums' in genre_tgm ({run.name}) ==")
all_hit = [i for i, o in recs.items() if any(is_target(t["term"]) for t in o["genre_tgm"])]
dev_hit = [i for i in all_hit if i in dev_gold]
print(f"all valid records : {len(all_hit)} of {len(recs)}")
print(f"dev gold records  : {len(dev_hit)} of {sum(1 for i in recs if i in dev_gold)}")

# ---- b) ----
print("\n== b) 15 most frequent terms across all valid records (AI output only) ==")
for field, label in (("genre_tgm", "genre_tgm"), ("subjects_lcsh", "subjects_lcsh")):
    c = collections.Counter(t["term"] for o in recs.values() for t in o[field])
    print(f"\n{label}  ({sum(c.values())} terms, {len(c)} distinct)")
    for term, n in c.most_common(15): print(f"  {n:4d}  {term}")

# ---- c) ----
def pooled(drop_target):
    pa = na = pg = ng = ea = eg = 0
    for i in sorted(dev_gold):
        if i not in recs: continue
        o = recs[i]; cat = catalog[i]
        ai = [t["term"] for t in o["subjects_lcsh"]] + [t["term"] for t in o["genre_tgm"]]
        if drop_target: ai = [t for t in ai if not is_target(t)]
        gold = split_terms(cat["Subjects (LCSH)"]) + split_terms(cat["Subjects (LCTGM)"])
        a = [credit(t, gold) for t in ai]; g = [credit(t, ai) for t in gold]
        pa += sum(a); ea += sum(c == 1.0 for c in a); na += len(ai)
        pg += sum(g); eg += sum(c == 1.0 for c in g); ng += len(gold)
    return dict(n_ai=na, precision=pa / na, recall=pg / ng, strict_precision=ea / na, strict_recall=eg / ng)

print("\n== c) 30 DEV gold records, pooled subjects ==")
now, wo = pooled(False), pooled(True)
print(f"{'':32s}{'AI terms':>9s}{'precision':>11s}{'recall':>9s}{'strict P':>10s}{'strict R':>10s}")
for label, d in (("as it is now", now), ("'Photograph albums' removed", wo)):
    print(f"{label:32s}{d['n_ai']:9d}{d['precision']:11.3f}{d['recall']:9.3f}{d['strict_precision']:10.3f}{d['strict_recall']:10.3f}")

# ---- d) ----
KEYS = ("album", "scrapbook", "mount", "page", "clipping", "postcard", "stereograph", "negative", "cabinet", "carte", "snapshot",
        "photograph", "print", "reproduction", "copy", "copies", "illustration", "drawing", "painting", "engraving", "map", "document", "manuscript", "newspaper")
print("\n== d) terms in vocab_tgm.txt that may describe the page, mount or physical object (listed only) ==")
for line in pathlib.Path("vocab_tgm.txt").read_text(encoding="utf-8").splitlines():
    t = line.strip()
    if t and any(k in t.lower() for k in KEYS): print("  ", t)
