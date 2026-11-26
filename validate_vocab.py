"""Check AI subject terms against id.loc.gov and compute a confidence score per record.
Usage:  python3 validate_vocab.py --prompt v2.1      (writes outputs/<run>/validation.csv)
Checks (objective):   does the main heading resolve in LCSH / LC names (LCSH terms) or TGM (genre terms)?
                      Headings listed in vocab_local.txt count as 'local': not invalid, but not authorized (half credit).
Not checked:          whether a subdivision is allowed under a heading (pattern rules) - a cataloger must judge that.
Confidence score (0-100) is a STARTING heuristic to be calibrated against your gold set:
   40% vocabulary validity | 30% model's own confidences | 20% grounding (visible-text / landmark basis) | 10% not flagged
Tiers: >=75 sample-check, 50-74 sample review, <50 full review.
"""
import argparse, csv, json, pathlib
from idloc import status

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v1")
ap.add_argument("--model", default="claude-sonnet-5-5")
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
local = set(l.strip() for l in open("vocab_local.txt", encoding="utf-8")) if pathlib.Path("vocab_local.txt").exists() else set()

def check_lcsh(term):
    if term in local: return "local"
    return status(["lcsh", "names"], term.split("--")[0])

W = {"high": 1.0, "medium": 0.6, "low": 0.2}
rows = []
for p in sorted(run.glob("*.json")):
    rec = json.loads(p.read_text(encoding="utf-8"))
    if not rec["valid"]:
        rows.append({"id": rec["id"], "valid_json": "N", "tier": "full review", "confidence": 0}); continue
    o = rec["output"]
    ls = [t["term"] for t in o["subjects_lcsh"]]; ts = [t["term"] for t in o["genre_tgm"]]
    lstat = [check_lcsh(t) for t in ls]; tstat = [status(["tgm"], t.split("--")[0]) for t in ts]
    allstat = lstat + tstat
    vocab = (sum(s == "authorized" for s in allstat) + 0.5 * sum(s in ("variant", "local") for s in allstat)) / len(allstat) if allstat else 0.5
    confs = [t["confidence"] for t in o["subjects_lcsh"] + o["genre_tgm"] + o["depicted_places"]] + [o["date_estimate"]["confidence"]]
    self_conf = sum(W[c] for c in confs) / len(confs) if confs else 0.5
    places = o["depicted_places"]
    ground = (sum(p["basis"] in ("visible_text", "landmark") for p in places) / len(places)) if places else 0.5
    named = [p for p in o["depicted_people"] if p["name_source"] != "none"]
    flagged = o["uncertainty_flag"]["needs_review"]
    score = round(100 * (0.4 * vocab + 0.3 * self_conf + 0.2 * ground + 0.1 * (0 if flagged else 1)))
    tier = "sample-check" if score >= 75 else "sample review" if score >= 50 else "full review"
    rows.append({"id": rec["id"], "valid_json": "Y", "lcsh_terms": len(ls), "lcsh_main_authorized": sum(s == "authorized" for s in lstat),
                 "lcsh_local": sum(s == "local" for s in lstat),
                 "lcsh_not_found": "; ".join(t for t, s in zip(ls, lstat) if s == "none"),
                 "tgm_terms": len(ts), "tgm_authorized": sum(s == "authorized" for s in tstat),
                 "tgm_not_found": "; ".join(t for t, s in zip(ts, tstat) if s == "none"),
                 "names_from_text": len(named), "model_flagged": "Y" if flagged else "N",
                 "confidence": score, "tier": tier})
fields = ["id","valid_json","lcsh_terms","lcsh_main_authorized","lcsh_local","lcsh_not_found","tgm_terms","tgm_authorized",
          "tgm_not_found","names_from_text","model_flagged","confidence","tier"]
with open(run / "validation.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
print("wrote", run / "validation.csv", len(rows), "records")
for r in rows: print(r["id"], r.get("confidence"), r.get("tier"))
