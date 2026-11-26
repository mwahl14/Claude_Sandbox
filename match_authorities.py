"""Reconcile the places the AI found to authority records.
Usage:  python3 match_authorities.py --prompt v2 [--gold-only]
Sources: LC names (LCNAF, includes geographic names), LC subject headings (LCSH), Wikidata, and GeoNames (optional).
GeoNames needs a free account: sign up at geonames.org, enable free web services, then run
    export GEONAMES_USERNAME=your_username        (skipped if not set)
Writes outputs/<run>/authorities.csv - one row per AI place, with the top candidate from each source.
STATUS meaning:   match = a source returned a heading equal to the place name (or the name plus a qualifier, e.g. 'Seattle (Wash.)')
                  candidate = results found but none equal -> a cataloger must choose
                  no result = nothing found in any source
Matches are SUGGESTIONS. The script never writes anything into catalog records.
"""
import argparse, csv, json, os, pathlib, re, time, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v1")
ap.add_argument("--model", default="claude-sonnet-5-5")
ap.add_argument("--gold-only", action="store_true", help="only records with in_gold_set = Y")
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
gold = {r["id"] for r in csv.DictReader(open("manifest.csv", encoding="utf-8")) if r["in_gold_set"] == "Y"}
GEO_USER = os.environ.get("GEONAMES_USERNAME")
UA = {"User-Agent": "prosch-metadata-study/0.1"}

cache_file = pathlib.Path("authority_cache.json")
cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}

def get_json(url, key):
    if key in cache: return cache[key]
    data = {}
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8")); break
        except OSError:
            time.sleep(2 * (attempt + 1))
    cache[key] = data; cache_file.write_text(json.dumps(cache)); time.sleep(0.5)
    return data

norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
def is_match(label, query):
    l, q = norm(label), norm(query)
    return l == q or l.startswith(q + " (") or l.startswith(q + ",")

def lc(service, q):
    path = {"names": "authorities/names", "lcsh": "authorities/subjects"}[service]
    d = get_json(f"https://id.loc.gov/{path}/suggest2?" + urllib.parse.urlencode({"q": q, "count": 5}), f"{service}|{q}")
    return [(h.get("aLabel", ""), h.get("uri", "")) for h in d.get("hits", [])]

def wikidata(q):
    d = get_json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": q, "language": "en", "format": "json", "limit": 5}), f"wd|{q}")
    return [(h.get("label", ""), h.get("id", ""), h.get("description", "")) for h in d.get("search", [])]

def geonames(q):
    if not GEO_USER: return []
    d = get_json("http://api.geonames.org/searchJSON?" + urllib.parse.urlencode(
        {"q": q, "maxRows": 5, "username": GEO_USER, "country": "US", "adminCode1": "WA"}), f"gn|{q}")
    return [(h.get("name", ""), str(h.get("geonameId", "")), h.get("fcodeName", "")) for h in d.get("geonames", [])]

def clean(place):
    """'Seattle, Washington' -> 'Seattle'; keep the first part for lookup"""
    return place.split(",")[0].strip()

rows = []
for p in sorted(run.glob("*.json")):
    rec = json.loads(p.read_text(encoding="utf-8"))
    if not rec["valid"] or (args.gold_only and rec["id"] not in gold): continue
    for pl in rec["output"]["depicted_places"]:
        q = clean(pl["place"])
        names, subj, wd, gn = lc("names", q), lc("lcsh", q), wikidata(q), geonames(q)
        hit = any(is_match(l, q) for l, _ in names + subj) or any(is_match(l, q) for l, _, _ in wd) or any(is_match(l, q) for l, _, _ in gn)
        status = "match" if hit else ("candidate" if (names or subj or wd or gn) else "no result")
        first = lambda lst, i=0: lst[0][i] if lst else ""
        rows.append({"id": rec["id"], "ai_place": pl["place"], "basis": pl["basis"], "confidence": pl["confidence"], "status": status,
                     "lcnaf_label": first(names), "lcnaf_uri": first(names, 1),
                     "lcsh_label": first(subj), "lcsh_uri": first(subj, 1),
                     "wikidata_label": first(wd), "wikidata_qid": first(wd, 1), "wikidata_description": first(wd, 2),
                     "geonames_name": first(gn), "geonames_id": first(gn, 1)})
fields = ["id","ai_place","basis","confidence","status","lcnaf_label","lcnaf_uri","lcsh_label","lcsh_uri",
          "wikidata_label","wikidata_qid","wikidata_description","geonames_name","geonames_id"]
with open(run / "authorities.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
print("wrote", run / "authorities.csv", len(rows), "places")
for s in ("match", "candidate", "no result"): print(s, sum(r["status"] == s for r in rows))
if not GEO_USER: print("(GeoNames skipped: GEONAMES_USERNAME not set)")
