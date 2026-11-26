"""DRAFT revised confidence score (term-level review flags + a record tier). NOT used by anything else yet.
Does not change validate_vocab.py, outputs/ or the catalog.  NO API calls.

Usage:  SSL_CERT_FILE=/etc/ssl/cert.pem python3 confidence_v2.py --prompt v3              (writes confidence_v2_v3.csv + confidence_v2_v3_terms.csv)
        SSL_CERT_FILE=/etc/ssl/cert.pem python3 confidence_v2.py --prompt v3 --evaluate   (also compares with gold precision, dev records only)
By default the 10 holdout records are skipped; --include-holdout is for one final test of the finished formula.

WHY (from calibrate.py): the current score does not rank records by gold precision, the needs_review flag is true on every record,
and local headings are penalized although they match gold at least as well as authorized ones. The one signal that did work was the
model's own 'low' confidence on a single term (mean gold credit .10 against .25-.28 for high/medium).

THE DRAFT
  A subject term is FLAGGED for review when:   the model gave it 'low' confidence,   OR   its main heading is not authorized
  (not found at id.loc.gov and not a local catalog heading; a spelling variant also counts).   Local headings are NOT penalized.
  The review sheet can show these flags so the reviewer starts with the flagged terms.
  Record score (0-100), subject terms only:
      v2a  = 100 * (1 - share of terms flagged)
      v2b  = v2a - 5 * (terms - 5) when a record has more than 5 terms   (more terms went with lower precision; the 5 is a round number, not fitted)
  Tiers use the same cut-offs as today: >= 75 sample-check, 50-74 sample review, < 50 full review.
Not covered: places, dates, titles and descriptions have no flags here (they are checked by score.py / by the reviewer).
"""
import argparse, csv, html, json, math, pathlib, re
from term_flags import term_flag

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v3"); ap.add_argument("--model", default="claude-sonnet-5-5")
ap.add_argument("--evaluate", action="store_true", help="compare with gold precision (gold records, dev only)")
ap.add_argument("--include-holdout", action="store_true")
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
old = {r["id"]: r for r in csv.DictReader(open(run / "validation.csv", encoding="utf-8"))} if (run / "validation.csv").exists() else {}
tier_of = lambda s: "sample-check" if s >= 75 else "sample review" if s >= 50 else "full review"

records, terms = [], []
for p in sorted(run.glob("[0-9]*.json"), key=lambda p: int(p.stem)):
    rec = json.loads(p.read_text(encoding="utf-8")); i = rec["id"]; m = manifest.get(i, {})
    if m.get("holdout") == "Y" and not args.include_holdout: continue
    if not rec["valid"]: continue
    o = rec["output"]; n_flag = 0; reasons_all = []
    items = [("lcsh", t) for t in o["subjects_lcsh"]] + [("tgm", t) for t in o["genre_tgm"]]
    for kind, t in items:
        flagged, why, st = term_flag(kind, t["term"], t["confidence"])
        reasons = [why] if flagged else []
        n_flag += bool(reasons)
        terms.append(dict(id=i, field=kind, term=t["term"], model_confidence=t["confidence"], vocab_status=st,
                          review_flag="Y" if flagged else "N", reasons=why))
    n = len(items)
    v2a = round(100 * (1 - n_flag / n)) if n else 50                    # no terms: nothing to check, middle tier
    v2b = max(0, round(v2a - 5 * max(0, n - 5)))
    records.append(dict(id=i, n_terms=n, n_flagged=n_flag, score_v2a=v2a, tier_v2a=tier_of(v2a), score_v2b=v2b, tier_v2b=tier_of(v2b),
                        old_score=old.get(i, {}).get("confidence", ""), old_tier=old.get(i, {}).get("tier", "")))

for name, rows in ((f"confidence_v2_{args.prompt}.csv", records), (f"confidence_v2_{args.prompt}_terms.csv", terms)):
    with open(name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
from collections import Counter
print(f"wrote confidence_v2_{args.prompt}.csv ({len(records)} records) and confidence_v2_{args.prompt}_terms.csv ({len(terms)} terms)")
print("terms flagged:", sum(t["review_flag"] == "Y" for t in terms), "of", len(terms))
for k in ("tier_v2a", "tier_v2b", "old_tier"):
    print(f"{k}:", dict(Counter(r[k] for r in records)))

if args.evaluate:
    # ---- helpers copied from score.py (same matching rules) ----
    def norm(t):
        t = t.lower().replace("&", "and"); t = re.sub(r"\s*--\s*", "--", t); return re.sub(r"\s+", " ", t).strip().rstrip(".")
    def main_(t): return norm(t.split("--")[0])
    def split_terms(s): return [re.sub(r"\s+", " ", t).strip() for t in html.unescape(s or "").split(";") if t.strip()]
    def credit(term, others):
        n, m = norm(term), main_(term); best = 0.0
        for o in others:
            if norm(o) == n: return 1.0
            if main_(o) == m: best = 0.5
        return best
    def pearson(x, y):
        n = len(x)
        if n < 3: return float("nan")
        mx, my = sum(x) / n, sum(y) / n; sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
        return float("nan") if sx == 0 or sy == 0 else sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)
    catalog = {r["CONTENTdm number"]: r for r in csv.DictReader(
        open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}
    dev = {i for i, r in manifest.items() if r["in_gold_set"] == "Y" and r["holdout"] != "Y"}
    tmap = {}
    for t in terms: tmap.setdefault(t["id"], []).append(t)
    rows = []
    for r in records:
        if r["id"] not in dev or not tmap.get(r["id"]): continue
        gold = split_terms(catalog[r["id"]]["Subjects (LCSH)"]) + split_terms(catalog[r["id"]]["Subjects (LCTGM)"])
        cr = [credit(t["term"], gold) for t in tmap[r["id"]]]
        rows.append(dict(r, precision=sum(cr) / len(cr)))
    print(f"\n=== evaluation on {len(rows)} dev gold records of {args.prompt} (gold precision per record) ===")
    prec = [r["precision"] for r in rows]
    print(f"mean precision {sum(prec) / len(prec):.3f}")
    print("correlation with precision:  " + "   ".join(f"{k} {pearson([float(r[k]) for r in rows if r[k] != ''], [r['precision'] for r in rows if r[k] != '']):+.2f}"
                                                  for k in ("old_score", "score_v2a", "score_v2b")) + "   (old_score = current validate_vocab.py score)")
    print("mean precision by tier (records):")
    for key in ("old_tier", "tier_v2a", "tier_v2b"):
        cells = []
        for tier in ("sample-check", "sample review", "full review"):
            ps = [r["precision"] for r in rows if r[key] == tier]
            cells.append(f"{tier} {sum(ps) / len(ps):.3f} ({len(ps)})" if ps else f"{tier} - (0)")
        print(f"  {key:9s} " + "  |  ".join(cells))
    fl = [tmap_t for r in rows for tmap_t in tmap[r["id"]]]
    credits = []
    for r in rows:
        gold = split_terms(catalog[r["id"]]["Subjects (LCSH)"]) + split_terms(catalog[r["id"]]["Subjects (LCTGM)"])
        credits += [(t["review_flag"], credit(t["term"], gold)) for t in tmap[r["id"]]]
    for flag, label in (("Y", "flagged terms"), ("N", "unflagged terms")):
        cs = [c for f, c in credits if f == flag]
        print(f"term level: {label:16s} n={len(cs):3d}  mean gold credit {sum(cs) / len(cs):.3f}" if cs else f"{label}: none")
