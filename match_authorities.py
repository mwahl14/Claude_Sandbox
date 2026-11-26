"""Reconcile the places the AI found to authority records (improved version).
Usage:  python3 match_authorities.py --prompt v3 --gold-only [--out authorities_v2.csv]
Sources: LC names (LCNAF), LC subject headings (LCSH), Wikidata, and GeoNames (optional; needs GEONAMES_USERNAME, not used here).
Writes outputs/<run>/<out> (default authorities.csv), one row per AI place. Matches are SUGGESTIONS for a cataloger; nothing is written to the catalog.

HOW A PLACE IS LOOKED UP (all rules, no AI call)
  1. Take the AI's place text, drop (parenthetical remarks) and state words, and pull out the named things in it: street names
     ("Fourth Avenue", "James Street"), the comma-separated parts that look like names ("Alki Point", "Kitsap County", "Seattle").
     Descriptive wording ("Southeast corner of", "near", "waterfront from") is ignored. The first named thing is the PRIMARY entity.
  2. City context: if this place or another place of the same record names Seattle, headings are tried as "Name (Seattle, Wash.)" first,
     then "Name (Wash.)". This is how LC writes local place headings.
  3. Each heading is looked up as an EXACT label at id.loc.gov (names, then subjects). A hit means that authority record exists with that label.
  4. Wikidata is searched for the entity, but only results whose description mentions Washington state or a nearby place are kept; the top
     result that was rejected (for example a town in France) is shown in wikidata_rejected_top so wrong matches stay visible.
STATUS:  match   = an exact LC label was found for the primary entity
         broader = no exact label for the primary entity, but one for another named thing in the text (usually the city)
         candidate = no LC label, but a Washington-filtered Wikidata result exists for the primary entity
         no result = nothing found
An exact label proves that the heading exists, not that it is the right place for the photograph: a cataloger still decides.
"""
import argparse, csv, json, os, pathlib, re, time, urllib.error, urllib.parse, urllib.request

STATE_WORDS = {"washington", "wash.", "wash", "wa", "washington state", "washington (state)", "washington territory", "territory", "u.s.", "usa", "united states"}
DESCRIPTIVE = re.compile(r"\b(near|looking|from|between|toward|towards|across|side|corner|at|on the site of|identified)\b")   # lower-case wording that describes, not names
LEAD_WORDS = {"near", "on", "from", "between", "at", "in", "west", "east", "north", "south", "corner", "intersection", "waterfront", "southeast",
              "southwest", "northeast", "northwest", "building", "upper", "lower", "view", "shore", "site", "looking", "south end", "city"}
STREET = re.compile(r"(?:(?:North|South|East|West)\s+)?(?:[A-Z][A-Za-z.']*\s+)*?[A-Z][A-Za-z.']*\s(?:Avenue|Street|Way|Road|Place|Boulevard|Alley)(?:\s+(?:North|South|East|West|[NSEW]\.?)\b)?")
NEARBY = re.compile(r"Washington(?!,?\s*D\.?C)|Seattle|King County|Puget Sound|Kitsap|Chelan|Wenatchee|Tacoma|Snohomish|Pierce County|Bainbridge", re.I)

def entities(place):
    """named things in an AI place string, in order of appearance (first = primary). Pure function: no network."""
    text = re.sub(r"\([^)]*\)", " ", place or "")
    out = []
    def add(x):
        x = re.sub(r"\s+", " ", x).strip(" .,;")
        if x and x.lower() not in STATE_WORDS and x not in out and len(x.split()) <= 6: out.append(x)
    for part in [p.strip() for p in text.split(",")]:
        if not part or part.lower() in STATE_WORDS: continue
        streets = [m.group(0) for m in STREET.finditer(part)]
        if streets:
            for s in streets: add(s)
        elif part.split()[0].lower() not in LEAD_WORDS and not part[0].islower() and not re.match(r"(?i)^(the|a|an)\b", part) and not DESCRIPTIVE.search(part):
            add(re.sub(r"\s+Washington$", "", part))
    return out

def city_context(places):
    """'Seattle' if any place of the record names it (including hedges such as '(probably Seattle)')"""
    return "Seattle" if any("seattle" in (p or "").lower() for p in places) else ""

def label_variants(entity, city):
    base = re.sub(r"\s+(North|South|East|West|[NSEW]\.?)$", "", entity) if STREET.fullmatch(entity) else entity
    names = [entity] + ([base] if base != entity else [])
    out = []
    for n in names:
        if city and n != city: out.append(f"{n} ({city}, Wash.)")
        out.append(f"{n} (Wash.)")
    return out

norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())

# ---------------------------------------------------------------- network (only runs as a script)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="v1"); ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--gold-only", action="store_true", help="only records with in_gold_set = Y")
    ap.add_argument("--out", default="authorities.csv")
    args = ap.parse_args()
    run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
    gold = {r["id"] for r in csv.DictReader(open("manifest.csv", encoding="utf-8")) if r["in_gold_set"] == "Y"}
    UA = {"User-Agent": "prosch-metadata-study/0.1"}
    cache_file = pathlib.Path("authority_cache.json")
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    opener = urllib.request.build_opener(NoRedirect)

    def fail(key, err):   # never cache a failure as an empty answer
        raise SystemExit(f"Lookup failed for {key!r}: {err!r}\nNothing cached for it. If this is a certificate error, run with SSL_CERT_FILE=/etc/ssl/cert.pem in front of the command.")

    def lc_exact(service, label):
        """URI if an authority record has exactly this label, else '' (cached; 404 is a real answer)"""
        key = f"lcl|{service}|{label}"
        if key in cache: return cache[key]
        url = f"https://id.loc.gov/authorities/{service}/label/" + urllib.parse.quote(label)
        err = None
        for attempt in range(5):
            try:
                opener.open(urllib.request.Request(url, headers=UA), timeout=30); uri = ""; break       # 200 without redirect: no record
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303): uri = e.headers.get("Location", ""); break
                if e.code == 404: uri = ""; break
                err = e; time.sleep(int(e.headers.get("Retry-After", "")) if e.code == 429 and e.headers.get("Retry-After", "").isdigit() else 15 * (attempt + 1))
            except OSError as e: err = e; time.sleep(2 * (attempt + 1))
        else: fail(key, err)
        cache[key] = uri; cache_file.write_text(json.dumps(cache)); time.sleep(0.3)
        return uri

    def wikidata(q):
        key = f"wd10|{q}"
        if key not in cache:
            url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({"action": "wbsearchentities", "search": q, "language": "en", "format": "json", "limit": 10})
            err, data = None, None
            for attempt in range(5):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as resp: data = json.loads(resp.read().decode("utf-8")); break
                except urllib.error.HTTPError as e:
                    err = e; w = e.headers.get("Retry-After", "") if e.code == 429 else ""; time.sleep(int(w) if w.isdigit() else 15 * (attempt + 1))
                except OSError as e: err = e; time.sleep(2 * (attempt + 1))
            if data is None: fail(key, err)
            cache[key] = [(h.get("label", ""), h.get("id", ""), h.get("description", "")) for h in data.get("search", [])]
            cache_file.write_text(json.dumps(cache)); time.sleep(2.0)
        return cache[key]

    rows = []
    for p in sorted(run.glob("[0-9]*.json"), key=lambda p: int(p.stem)):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if not rec["valid"] or (args.gold_only and rec["id"] not in gold): continue
        places = [pl["place"] for pl in rec["output"]["depicted_places"]]; city_all = city_context(places)
        for pl in rec["output"]["depicted_places"]:
            ents = entities(pl["place"]); city = "Seattle" if "seattle" in pl["place"].lower() else city_all
            only_city = not ents and "seattle" in pl["place"].lower()          # e.g. 'South end of Seattle': only the containing city can be matched
            if only_city: ents = ["Seattle"]
            context = "" if not city else ("Seattle (in this place)" if "seattle" in pl["place"].lower() else "Seattle (from another place in the record)")
            found = []                                   # (entity, label, uri, source)
            for e in ents:
                for label in label_variants(e, city):
                    hit = next(((s, u) for s in ("names", "subjects") for u in [lc_exact(s, label)] if u), None)
                    if hit: found.append((e, label, hit[1], hit[0])); break
            wd_pick, wd_rejected = None, ""
            if ents:
                res = wikidata(ents[0]); kept = [r for r in res if NEARBY.search(r[2] or "")]
                wd_pick = next((r for r in kept if norm(r[0]) == norm(ents[0])), kept[0] if kept else None)
                if res and (not kept or res[0] != (wd_pick or res[0])): wd_rejected = f"{res[0][0]} ({res[0][2][:60]})"
            primary = next((f for f in found if f[0] == ents[0]), None) if ents else None
            status = ("broader" if (primary and only_city) else "match" if primary else "broader" if found else "candidate" if wd_pick else "no result")
            best = primary or (found[0] if found else ("", "", "", ""))
            rows.append({"id": rec["id"], "ai_place": pl["place"], "basis": pl["basis"], "confidence": pl["confidence"], "status": status,
                         "entities": " | ".join(ents), "context": context, "lc_entity": best[0], "lc_label": best[1], "lc_uri": best[2], "lc_source": best[3],
                         "wikidata_label": wd_pick[0] if wd_pick else "", "wikidata_qid": wd_pick[1] if wd_pick else "",
                         "wikidata_description": wd_pick[2] if wd_pick else "", "wikidata_rejected_top": wd_rejected})
    fields = ["id", "ai_place", "basis", "confidence", "status", "entities", "context", "lc_entity", "lc_label", "lc_uri", "lc_source",
              "wikidata_label", "wikidata_qid", "wikidata_description", "wikidata_rejected_top"]
    with open(run / args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    print("wrote", run / args.out, len(rows), "places")
    for s in ("match", "broader", "candidate", "no result"): print(s, sum(r["status"] == s for r in rows))

if __name__ == "__main__":
    main()
