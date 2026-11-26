"""Pull a sample of AI subject terms that did NOT match the gold record into a sheet for you to judge.
Usage:  python3 sample_unmatched.py --prompt v2.1            (20 terms from the 30 DEV records)
        python3 sample_unmatched.py --prompt v2.1 --n 30 --subset all
Writes:  outputs/<run>/unmatched_review.csv   (open in Excel)
For each term, look at the photo (images/<id>.jpg) and the gold subjects, then fill in 'verdict':
   wrong                  the term does not fit the photo, or is unsupported by what is visible
   defensible             a reasonable heading for the photo that catalogers simply did not assign
   gold_incomplete        the term is clearly right and the gold record is missing something it should have
   gold_outdated          the term is current, the gold heading is superseded
   too_generic            true but so broad it adds little
   name_unsupported       a person, building, or business name the image does not support
Default is the DEV records only, so the 10 holdout records stay unseen while you tune prompts.
"""
import argparse, csv, html, json, pathlib, random, re

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v2.1")
ap.add_argument("--model", default="claude-sonnet-5-5")
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--subset", default="dev", choices=["dev", "holdout", "all"])
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
random.seed(7)

def norm(t):
    t = t.lower().replace("&", "and")
    t = re.sub(r"\s*--\s*", "--", t)
    return re.sub(r"\s+", " ", t).strip().rstrip(".")
def main(t): return norm(t.split("--")[0])
def split_terms(s): return [re.sub(r"\s+", " ", t).strip() for t in html.unescape(s or "").split(";") if t.strip()]
def credit(term, gold):
    best = 0.0
    for g in gold:
        if norm(g) == norm(term): return 1.0
        if main(g) == main(term): best = 0.5
    return best

manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
catalog = {r["CONTENTdm number"]: r for r in csv.DictReader(
    open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}
local = set(l.strip() for l in open("vocab_local.txt", encoding="utf-8")) if pathlib.Path("vocab_local.txt").exists() else set()

pool = {}   # record id -> list of candidate rows
for p in sorted(run.glob("*.json")):
    rec = json.loads(p.read_text(encoding="utf-8")); i = rec["id"]; m = manifest.get(i, {})
    if m.get("in_gold_set") != "Y" or not rec["valid"]: continue
    sub = "holdout" if m.get("holdout") == "Y" else "dev"
    if args.subset != "all" and sub != args.subset: continue
    cat = catalog[i]
    gold = split_terms(cat["Subjects (LCSH)"]) + split_terms(cat["Subjects (LCTGM)"])
    for field, key in (("lcsh", "subjects_lcsh"), ("tgm", "genre_tgm")):
        for t in rec["output"][key]:
            if credit(t["term"], gold) == 0.0:
                pool.setdefault(i, []).append({
                    "id": i, "subset": sub, "image_file": f"images/{i}.jpg", "gold_title": cat["Title"],
                    "gold_subjects": " ; ".join(gold), "ai_term": t["term"], "field": field,
                    "ai_confidence": t["confidence"], "term_type": "local heading" if t["term"] in local else "authorized/TGM",
                    "ai_description": rec["output"]["description"], "verdict": "", "notes": ""})

# spread the sample across records: round-robin, at most 2 terms per record
for v in pool.values(): random.shuffle(v)
ids = sorted(pool); random.shuffle(ids)
sample = []
for round_ in range(2):
    for i in ids:
        if len(sample) < args.n and len(pool[i]) > round_: sample.append(pool[i][round_])
total_unmatched = sum(len(v) for v in pool.values())
fields = ["id","subset","image_file","gold_title","gold_subjects","ai_term","field","ai_confidence","term_type",
          "ai_description","verdict","notes"]
with open(run / "unmatched_review.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(sample)
print(f"{total_unmatched} unmatched AI terms in {len(pool)} {args.subset} records; wrote {len(sample)} to {run / 'unmatched_review.csv'}")
