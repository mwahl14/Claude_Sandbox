"""Compare two runs side by side on the 30 DEV gold records (for model A vs model B on the same prompt). NO API calls.
Usage:  python3 compare_models.py --a v3_claude-sonnet-5-5 --b v3_claude-haiku-5-5
Needs for BOTH runs:  describe.py output, validate_vocab.py (validation.csv) and score.py (scores.csv + summary.csv) already run.
Prints a table and writes model_comparison_<subset>.md and .csv (dev by default; --subset holdout for the final test). Also lists the 5 records where the two runs differ most
(by the gap in per-record precision plus recall against gold); it only LISTS them: judging which run was right is yours to do.
Tokens are reported as the cost measure (no prices are assumed). The 10 holdout records are not used.
"""
import argparse, csv, json, pathlib

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True); ap.add_argument("--b", required=True)
ap.add_argument("--subset", choices=["dev", "holdout"], default="dev", help="which gold records to compare (holdout: final evaluation only)")
args = ap.parse_args()
manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
dev = {i for i, r in manifest.items() if r["in_gold_set"] == "Y" and (r["holdout"] == "Y") == (args.subset == "holdout")}   # the chosen subset
summary = list(csv.DictReader(open("summary.csv", encoding="utf-8")))

def load(name):
    run = pathlib.Path("outputs") / name
    recs = {}
    for p in run.glob("[0-9]*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r["id"] in dev: recs[r["id"]] = r
    val = {r["id"]: r for r in csv.DictReader(open(run / "validation.csv", encoding="utf-8")) if r["id"] in dev}
    scores = {r["id"]: r for r in csv.DictReader(open(run / "scores.csv", encoding="utf-8")) if r["id"] in dev}
    s = next((r for r in summary if r["run"] == name and r["subset"] == args.subset), None)
    if s is None: raise SystemExit(f"summary.csv has no {args.subset} row for {name}: run score.py for it first.")
    return dict(name=name, recs=recs, val=val, scores=scores, s=s)

A, B = load(args.a), load(args.b)
for X in (A, B):
    if len(X["recs"]) < len(dev): print(f"NOTE: {X['name']} has only {len(X['recs'])} of {len(dev)} dev records.")

def tot(X, k): return sum(r["provenance"][k] for r in X["recs"].values())
def valid(X): return sum(r["valid"] for r in X["recs"].values())
def tiers(X):
    from collections import Counter
    c = Counter(v["tier"] for v in X["val"].values()); return f"{c['sample-check']} / {c['sample review']} / {c['full review']}"
def terms(X): return sum(len(r["output"]["subjects_lcsh"]) + len(r["output"]["genre_tgm"]) for r in X["recs"].values() if r["valid"])
def flagged(X): return sum(v.get("model_flagged") == "Y" for v in X["val"].values())
S = lambda X, k: X["s"][k]
rows = [
    (f"Records ({args.subset})", len(A["recs"]), len(B["recs"])),
    ("Valid JSON", f"{valid(A)} of {len(A['recs'])}", f"{valid(B)} of {len(B['recs'])}"),
    ("Input tokens (total)", f"{tot(A, 'input_tokens'):,}", f"{tot(B, 'input_tokens'):,}"),
    ("Output tokens (total)", f"{tot(A, 'output_tokens'):,}", f"{tot(B, 'output_tokens'):,}"),
    ("Subject terms returned", terms(A), terms(B)),
    ("Pooled precision, partial / strict", f"{S(A, 'pooled_precision_partial')} / {S(A, 'pooled_precision_strict')}", f"{S(B, 'pooled_precision_partial')} / {S(B, 'pooled_precision_strict')}"),
    ("Pooled recall, partial / strict", f"{S(A, 'pooled_recall_partial')} / {S(A, 'pooled_recall_strict')}", f"{S(B, 'pooled_recall_partial')} / {S(B, 'pooled_recall_strict')}"),
    ("LCSH precision / recall (partial)", f"{S(A, 'lcsh_precision_partial')} / {S(A, 'lcsh_recall_partial')}", f"{S(B, 'lcsh_precision_partial')} / {S(B, 'lcsh_recall_partial')}"),
    ("TGM precision / recall (partial)", f"{S(A, 'tgm_precision_partial')} / {S(A, 'tgm_recall_partial')}", f"{S(B, 'tgm_precision_partial')} / {S(B, 'tgm_recall_partial')}"),
    ("Dates correct / partial / wrong", f"{S(A, 'date_correct')} / {S(A, 'date_partial')} / {S(A, 'date_wrong')}", f"{S(B, 'date_correct')} / {S(B, 'date_partial')} / {S(B, 'date_wrong')}"),
    ("Places correct / wrong", f"{S(A, 'place_correct')} / {S(A, 'place_wrong')}", f"{S(B, 'place_correct')} / {S(B, 'place_wrong')}"),
    ("Description-alt overlap (lower is better)", S(A, "mean_desc_alt_overlap"), S(B, "mean_desc_alt_overlap")),
    ("LCSH main validity / TGM validity", f"{S(A, 'lcsh_main_validity')} / {S(A, 'tgm_validity')}", f"{S(B, 'lcsh_main_validity')} / {S(B, 'tgm_validity')}"),
    ("Tiers: sample-check / sample review / full review", tiers(A), tiers(B)),
    ("Records where the model set needs_review = true", flagged(A), flagged(B)),
]
w0 = max(len(r[0]) for r in rows)
print(f"\n{'':{w0}s}  {args.a:>30s}  {args.b:>30s}")
for r in rows: print(f"{r[0]:{w0}s}  {str(r[1]):>30s}  {str(r[2]):>30s}")

def pr(X, i):
    s = X["scores"].get(i)
    if not s or s["valid_json"] != "Y" or not s.get("pooled_n_ai") or float(s["pooled_n_ai"]) == 0: return None
    return float(s["pooled_ai_partial"]) / float(s["pooled_n_ai"]), float(s["pooled_gold_partial"]) / float(s["pooled_n_gold"]), int(float(s["pooled_n_ai"]))
diffs = []
for i in sorted(dev, key=int):
    a, b = pr(A, i), pr(B, i)
    if a and b: diffs.append((abs(a[0] - b[0]) + abs(a[1] - b[1]), i, a, b))
diffs.sort(reverse=True)
print(f"\nSubset: {args.subset} ({len(dev)} gold records)"); print("Five records where the two runs differ most (precision/recall vs gold; listed only, not judged):")
print(f"{'id':>5s}  {'A prec/rec (terms)':>24s}  {'B prec/rec (terms)':>24s}  {'dates A / B':>22s}  {'place A / B':>20s}")
top = []
for gap, i, a, b in diffs[:5]:
    da, db = A["scores"][i]["date_grade"], B["scores"][i]["date_grade"]; pa, pb = A["scores"][i]["place_grade"], B["scores"][i]["place_grade"]
    print(f"{i:>5s}  {a[0]:7.2f} /{a[1]:5.2f} ({a[2]:2d})      {b[0]:7.2f} /{b[1]:5.2f} ({b[2]:2d})      {da + ' / ' + db:>22s}  {pa + ' / ' + pb:>20s}")
    top.append(dict(id=i, a_precision=round(a[0], 2), a_recall=round(a[1], 2), b_precision=round(b[0], 2), b_recall=round(b[1], 2), gap=round(gap, 2)))
with open(f"model_comparison_{args.subset}.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["measure", args.a, args.b]); w.writerows(rows)
    w.writerow([]); w.writerow(["most different records (id, A precision, A recall, B precision, B recall, gap)"])
    for t in top: w.writerow(list(t.values()))
with open(f"model_comparison_{args.subset}.md", "w", encoding="utf-8") as f:
    f.write(f"| Measure ({len(dev)} {args.subset} records) | {args.a} | {args.b} |\n|---|---|---|\n")
    for r in rows: f.write(f"| {r[0]} | {r[1]} | {r[2]} |\n")
print(f"\nwrote model_comparison_{args.subset}.md and model_comparison_{args.subset}.csv")
