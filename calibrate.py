"""Does the confidence score predict correctness?   NO API calls; changes nothing in outputs/ or validate_vocab.py.
Usage:  SSL_CERT_FILE=/etc/ssl/cert.pem python3 calibrate.py                 (runs v1, v2.1, v3)
        python3 calibrate.py --prompts v2.1,v3
Uses the 30 DEV gold records ONLY (holdout is excluded, so it can still be used to test a final formula once).

"Correct" here means "matches the catalogers' gold subjects" (pooled partial-credit precision per record, same method as score.py).
That is a rough yardstick: gold is from 2000-2001 and incomplete, and your 20-term review found many non-matching AI terms
were defensible or merely too generic, so real correctness is higher than gold precision.

Prints:  1) per run: correlation of the score and of each of its 4 parts with precision, and mean precision by tier
         2) the flag check (is needs_review ever false?)
         3) term level: does the model's own high/medium/low confidence predict whether a term matches gold?  does vocabulary status?
         4) a small weight search: weights picked on two runs, tested on the third (so it is not just fitting the same records)
Writes:  calibration_records.csv (one row per run and record) and calibration_terms.csv (one row per AI term), in this folder.
Needs the same helper the validator uses (idloc.py); lookups come from id_cache.json, so no network is needed unless a term is new.
"""
import argparse, csv, html, itertools, json, math, pathlib, re
from idloc import status

ap = argparse.ArgumentParser()
ap.add_argument("--prompts", default="v1,v2.1,v3"); ap.add_argument("--model", default="claude-sonnet-5-5")
args = ap.parse_args()

# ---- helpers copied from score.py (same matching rules) ----
def norm(t):
    t = t.lower().replace("&", "and"); t = re.sub(r"\s*--\s*", "--", t)
    return re.sub(r"\s+", " ", t).strip().rstrip(".")
def main(t): return norm(t.split("--")[0])
def split_terms(s): return [re.sub(r"\s+", " ", t).strip() for t in html.unescape(s or "").split(";") if t.strip()]
def credit(term, others):
    n, m = norm(term), main(term); best = 0.0
    for o in others:
        if norm(o) == n: return 1.0
        if main(o) == m: best = 0.5
    return best

W = {"high": 1.0, "medium": 0.6, "low": 0.2}
local = set(l.strip() for l in open("vocab_local.txt", encoding="utf-8"))
manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
catalog = {r["CONTENTdm number"]: r for r in csv.DictReader(
    open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}
dev = {i for i, r in manifest.items() if r["in_gold_set"] == "Y" and r["holdout"] != "Y"}

# ---- statistics without numpy ----
def pearson(x, y):
    n = len(x)
    if n < 3: return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return float("nan") if sx == 0 or sy == 0 else sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)
def ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]: j += 1
        for k in range(i, j + 1): r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r
def spearman(x, y): return pearson(ranks(x), ranks(y))
f3 = lambda v: "  n/a" if v != v else f"{v:5.2f}"

records, terms = [], []
for prompt in args.prompts.split(","):
    run = pathlib.Path("outputs") / f"{prompt}_{args.model}"
    val = {r["id"]: r for r in csv.DictReader(open(run / "validation.csv", encoding="utf-8"))}
    for p in sorted(run.glob("[0-9]*.json"), key=lambda p: int(p.stem)):
        rec = json.loads(p.read_text(encoding="utf-8")); i = rec["id"]
        if i not in dev or not rec["valid"]: continue
        o = rec["output"]; cat = catalog[i]
        gold = split_terms(cat["Subjects (LCSH)"]) + split_terms(cat["Subjects (LCTGM)"])
        ai = [("lcsh", t) for t in o["subjects_lcsh"]] + [("tgm", t) for t in o["genre_tgm"]]
        ai_terms = [t["term"] for _, t in ai]
        stats = []
        for kind, t in ai:
            st = ("local" if t["term"] in local else status(["lcsh", "names"], t["term"].split("--")[0])) if kind == "lcsh" \
                 else status(["tgm"], t["term"].split("--")[0])
            stats.append(st)
            terms.append(dict(run=prompt, id=i, field=kind, term=t["term"], model_confidence=t["confidence"], vocab_status=st,
                              credit=credit(t["term"], gold)))
        vocab = (sum(s == "authorized" for s in stats) + 0.5 * sum(s in ("variant", "local") for s in stats)) / len(stats) if stats else 0.5
        confs = [t["confidence"] for t in o["subjects_lcsh"] + o["genre_tgm"] + o["depicted_places"]] + [o["date_estimate"]["confidence"]]
        selfc = sum(W[c] for c in confs) / len(confs) if confs else 0.5
        places = o["depicted_places"]
        ground = sum(pl["basis"] in ("visible_text", "landmark") for pl in places) / len(places) if places else 0.5
        flagged = bool(o["uncertainty_flag"]["needs_review"])
        score = round(100 * (0.4 * vocab + 0.3 * selfc + 0.2 * ground + 0.1 * (0 if flagged else 1)))
        csv_score = int(val[i]["confidence"])
        prec = sum(credit(t, gold) for t in ai_terms) / len(ai_terms) if ai_terms else float("nan")
        rec_ = sum(credit(g, ai_terms) for g in gold) / len(gold) if gold else float("nan")
        records.append(dict(run=prompt, id=i, n_ai_terms=len(ai_terms), precision=prec, recall=rec_, vocab=vocab, self_conf=selfc,
                            ground=ground, flagged=int(flagged), score=score, score_in_validation_csv=csv_score, tier=val[i]["tier"]))

# integrity check: my recomputed score must equal validation.csv
bad = [r for r in records if r["score"] != r["score_in_validation_csv"]]
print(f"Recomputed confidence score matches validation.csv for {len(records) - len(bad)} of {len(records)} run-records"
      + ("" if not bad else f"  (MISMATCH, e.g. {bad[0]['run']} {bad[0]['id']}: {bad[0]['score']} vs {bad[0]['score_in_validation_csv']})"))

# ---------------------------------------------------------------- 1) per run
print("\n=== 1) Does the score track gold precision?  (30 dev records per run; records with no AI terms left out) ===")
print(f"{'run':6s}{'n':>3s} {'mean prec':>9s} {'r(score)':>9s} {'rho(score)':>10s} | r with precision for each part: {'vocab':>6s}{'self':>6s}{'ground':>7s}{'noflag':>7s}")
for prompt in args.prompts.split(",") + ["ALL"]:
    rs = [r for r in records if (prompt == "ALL" or r["run"] == prompt) and r["precision"] == r["precision"]]
    pr = [r["precision"] for r in rs]
    print(f"{prompt:6s}{len(rs):3d} {sum(pr) / len(pr):9.3f} {f3(pearson([r['score'] for r in rs], pr)):>9s} {f3(spearman([r['score'] for r in rs], pr)):>10s} |"
          f"{'':32s}{f3(pearson([r['vocab'] for r in rs], pr)):>6s}{f3(pearson([r['self_conf'] for r in rs], pr)):>6s}"
          f"{f3(pearson([r['ground'] for r in rs], pr)):>7s}{f3(pearson([1 - r['flagged'] for r in rs], pr)):>7s}")
print("\nMean gold precision by tier (number of records in brackets):")
print(f"{'run':6s}{'sample-check':>18s}{'sample review':>18s}{'full review':>16s}")
for prompt in args.prompts.split(",") + ["ALL"]:
    cells = []
    for tier in ("sample-check", "sample review", "full review"):
        rs = [r["precision"] for r in records if (prompt == "ALL" or r["run"] == prompt) and r["tier"] == tier and r["precision"] == r["precision"]]
        cells.append(f"{sum(rs) / len(rs):.3f} ({len(rs)})" if rs else "-")
    print(f"{prompt:6s}{cells[0]:>18s}{cells[1]:>18s}{cells[2]:>16s}")

# ---------------------------------------------------------------- 2) flag
print("\n=== 2) The needs_review flag (10% of the score) ===")
for prompt in args.prompts.split(","):
    rs = [r for r in records if r["run"] == prompt]
    print(f"{prompt:6s} flagged true on {sum(r['flagged'] for r in rs)} of {len(rs)} dev records")

# ---------------------------------------------------------------- 3) term level
print("\n=== 3) Term level: mean gold credit per AI term (1 = exact match, 0.5 = same main heading, 0 = none) ===")
def table(key, order):
    print(f"{key:18s}" + "".join(f"{prompt:>16s}" for prompt in args.prompts.split(",") + ["ALL"]))
    for val_ in order:
        cells = []
        for prompt in args.prompts.split(",") + ["ALL"]:
            ts = [t["credit"] for t in terms if (prompt == "ALL" or t["run"] == prompt) and t[key] == val_]
            cells.append(f"{sum(ts) / len(ts):.2f} (n={len(ts)})" if ts else "-")
        print(f"{val_:18s}" + "".join(f"{c:>16s}" for c in cells))
table("model_confidence", ["high", "medium", "low"])
print()
table("vocab_status", ["authorized", "variant", "local", "none"])

# ---------------------------------------------------------------- 4) weight search
print("\n=== 4) Weight search (exploratory): parts = vocab, self_conf, ground, noflag; weights in steps of 0.1 summing to 1 ===")
comps = lambda r: (r["vocab"], r["self_conf"], r["ground"], 1 - r["flagged"])
grid = [w for w in itertools.product(range(11), repeat=4) if sum(w) == 10]
def corr_for(weights, rs):
    rs = [r for r in rs if r["precision"] == r["precision"]]
    return pearson([sum(w / 10 * c for w, c in zip(weights, comps(r))) for r in rs], [r["precision"] for r in rs])
runs = args.prompts.split(",")
current = (4, 3, 2, 1)
print(f"{'weights (vocab,self,ground,noflag)':36s}{'chosen on':>14s}{'tested on':>12s}{'r (test)':>10s}{'r (train)':>10s}   current-weights r (test)")
for test in runs:
    train = [r for r in records if r["run"] != test]; tst = [r for r in records if r["run"] == test]
    best = max(grid, key=lambda w: (round(corr_for(w, train), 6) if corr_for(w, train) == corr_for(w, train) else -2))
    print(f"{str(tuple(w / 10 for w in best)):36s}{'+'.join(r for r in runs if r != test):>14s}{test:>12s}{f3(corr_for(best, tst)):>10s}{f3(corr_for(best, train)):>10s}   {f3(corr_for(current, tst))}")
allbest = max(grid, key=lambda w: corr_for(w, records) if corr_for(w, records) == corr_for(w, records) else -2)
print(f"\nBest weights on all three runs together: {tuple(w / 10 for w in allbest)}  r = {f3(corr_for(allbest, records))}   (current 0.4/0.3/0.2/0.1: r = {f3(corr_for(current, records))})")
print("The same 30 records appear in every run, so these are not independent samples; treat all of section 4 as a hint, not a result.")

for name, rows_ in (("calibration_records.csv", records), ("calibration_terms.csv", terms)):
    with open(name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_[0])); w.writeheader(); w.writerows(rows_)
print("\nwrote calibration_records.csv and calibration_terms.csv")
