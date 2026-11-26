"""Shared helper: look up headings at id.loc.gov (LCSH, LC names/LCNAF, TGM) with a local cache (id_cache.json)."""
import json, pathlib, re, time, urllib.parse, urllib.request

SERVICES = {"lcsh":  "https://id.loc.gov/authorities/subjects/suggest2",
            "names": "https://id.loc.gov/authorities/names/suggest2",
            "tgm":   "https://id.loc.gov/vocabulary/graphicMaterials/suggest2"}
CACHE_FILE = pathlib.Path("id_cache.json")
cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
norm = lambda s: re.sub(r"\s+", " ", s.strip().lower()).replace("&", "and")

def fetch_hits(service, label):
    key = f"{service}|{label}"
    if key in cache: return cache[key]
    url = SERVICES[service] + "?" + urllib.parse.urlencode({"q": label, "count": 10})
    hits, ok = [], False
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "prosch-metadata-study/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                hits = json.loads(resp.read().decode("utf-8")).get("hits", []); ok = True
            break
        except OSError:
            time.sleep(2 * (attempt + 1))
    if ok:                                   # only cache real answers, never failures
        cache[key] = hits; CACHE_FILE.write_text(json.dumps(cache))
    time.sleep(0.5)
    return hits

def status(service_list, label):
    """authorized | variant | none  (compares the heading given; callers pass the main heading)"""
    q = norm(label)
    for svc in service_list:
        for h in fetch_hits(svc, label):
            if norm(h.get("aLabel", "")) == q: return "authorized"
            if norm(h.get("vLabel", "")) == q or q in [norm(v) for v in h.get("more", {}).get("variantLabels", [])]:
                return "variant"
    return "none"
