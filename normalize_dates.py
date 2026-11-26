"""Turn the model's free-text date_estimate.value into the three date fields from the draft data dictionary.
NO API calls: plain rules, so the same input always gives the same output.

Usage as a module:   from normalize_dates import normalize ;  normalize("circa 1896")
Usage as a script:   python3 normalize_dates.py --prompt v3            (writes normalized_dates_v3.csv in this folder)
                     python3 normalize_dates.py --prompt v3 --check    (also compares with the 30 DEV gold Date-EDTF values)
The 10 holdout records are skipped unless you pass --include-holdout (do that only once, at the very end).

Output for each date (rules from PLAN.md / the DRAFT dictionary; confirm when the dictionary is approved):
  display  "Date of publication":  1905 | 1905? | approximately 1905 | June 21, 1905 | September, 1911 | between 1880 and 1889 | between 1880 and 1889?
  dates    hidden search field: years only, space-separated. Exact ranges list every year. Approximate or
           probable dates and ranges get 5 extra years on each side (approximately 1910 -> 1905 ... 1915).
  edtf     Date-EDTF: 1905 | 1905? | 1905~ | 1905-06-21 | 1911-09 | 1880/1889 | 1880?/1889?
  status   ok | multiple (several dates, check) | review (narrative or unclear: a cataloger decides) | unknown
Words meaning "approximately" (circa, ca., about, approx, early/mid/late) -> approximate.  Words meaning "probably"
(probably, possibly, likely, tentative, uncertain) -> uncertain.  Ranges that are approximate or uncertain get "?" on both ends.
Only the date at the START of each ';'-separated part is used; commentary in (parentheses) or later parts is ignored.
Assumptions to confirm: early/mid/late decade = approx. year +2 / +5 / +7; early/mid/late century = approx. years 0-33 / 34-66 / 67-99.
"""
import argparse, csv, html, json, pathlib, re

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MON_RE = "|".join(MONTHS) + r"|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec"
MON_NUM = {m: i + 1 for i, m in enumerate(MONTHS)}
MON_NUM.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
DASH = r"[-–—]"

ITEM = re.compile(rf"""
 (?P<iso>(?<!\d)(?P<iy>\d{{4}})-(?P<im>\d{{2}})-(?P<id>\d{{2}})(?!\d))
|(?P<mdy>\b(?P<mdm>{MON_RE})\.?\s+(?P<mdd>\d{{1,2}}),?\s+(?P<mdyr>\d{{4}}))
|(?P<my>\b(?P<mym>{MON_RE})\.?,?\s+(?P<myy>\d{{4}}))
|(?P<dd>(?<!\d)(?P<dd1>\d{{3}})0s\s*{DASH}\s*(?P<dd2>\d{{3}})0s)
|(?P<dyr>(?<!\d)(?P<dy1>\d{{3}})0s\s*{DASH}\s*(?P<dy2>\d{{4}})(?!\d))
|(?P<ydr>(?<!\d)(?P<yd1>\d{{4}})\s*{DASH}\s*(?P<yd2>\d{{3}})0s)
|(?P<btw>\bbetween\s+(?P<b1>\d{{4}})\s+and\s+(?P<b2>\d{{4}}))
|(?P<yr>(?<!\d)(?P<y1>\d{{4}})\s*(?:{DASH}|\bto\b)\s*(?P<y2>\d{{4}})(?!\d))
|(?P<qdec>\b(?P<qq>early|mid|late)[\s-]*(?P<qd>\d{{3}})0s)
|(?P<dec>(?<!\d)(?P<d0>\d{{3}})0s)
|(?P<cent>\b(?:(?P<cq>early|mid|late)[\s-]*)?(?P<cn>\d{{2}})(?:st|nd|rd|th)\s+century)
|(?P<year>(?<!\d)(?P<yy>\d{{4}})(?!\d))
""", re.X | re.I)

LEAD = re.compile(r"^\s*(?:(?:circa|ca\.?|c\.|about|approximately|approx\.?|probably|possibly|likely)\s*[:,]?\s+)+", re.I)
APPROX = re.compile(r"(circa|\bca\.?|\bc\.|about|approx\w*\.?)\s*$", re.I)
UNCERTAIN = re.compile(r"\b(probably|possibly|likely|tentative(ly)?|uncertain|perhaps)\b", re.I)
SHORT_PAREN = re.compile(r"\(\s*(possibly|probably|likely|tentative(ly)?|uncertain|perhaps)\s*\)", re.I)
SPAN = {"early": (0, 33), "mid": (34, 66), "late": (67, 99)}
OK_YEAR = lambda y: 1500 <= y <= 2100


def _items(seg):
    """date items found in one ';' part: list of dicts {kind, y1, y2, m, d, flag}"""
    flag_seg = "unc" if (UNCERTAIN.search(re.sub(r"\([^)]*\)", " ", seg)) or SHORT_PAREN.search(seg)) else None
    text = re.sub(r"\([^)]*\)", " ", seg)
    out = []
    for m in ITEM.finditer(text):
        g = m.lastgroup
        names = {k: v for k, v in m.groupdict().items() if v is not None}
        flag = flag_seg
        if APPROX.search(text[max(0, m.start() - 15):m.start()]): flag = "approx"
        elif text[m.end():m.end() + 1] == "?": flag = "unc"          # '1889?' or 'between 1880 and 1889?' (our own display format)
        it = None
        if "iso" in names:
            y, mo, d = int(names["iy"]), int(names["im"]), int(names["id"])
            if 1 <= mo <= 12 and 1 <= d <= 31: it = dict(kind="date", y1=y, y2=y, m=mo, d=d)
        elif "mdy" in names:
            it = dict(kind="date", y1=int(names["mdyr"]), y2=int(names["mdyr"]), m=MON_NUM[names["mdm"].lower()], d=int(names["mdd"]))
        elif "my" in names:
            it = dict(kind="month", y1=int(names["myy"]), y2=int(names["myy"]), m=MON_NUM[names["mym"].lower()])
        elif "dd" in names: it = dict(kind="range", y1=int(names["dd1"]) * 10, y2=int(names["dd2"]) * 10 + 9)
        elif "dyr" in names: it = dict(kind="range", y1=int(names["dy1"]) * 10, y2=int(names["dy2"]))
        elif "ydr" in names: it = dict(kind="range", y1=int(names["yd1"]), y2=int(names["yd2"]) * 10 + 9)
        elif "btw" in names: it = dict(kind="range", y1=int(names["b1"]), y2=int(names["b2"]))
        elif "yr" in names: it = dict(kind="range", y1=int(names["y1"]), y2=int(names["y2"]))
        elif "qdec" in names:
            base = int(names["qd"]) * 10
            it = dict(kind="year", y1=base + {"early": 2, "mid": 5, "late": 7}[names["qq"].lower()], y2=0); flag = "approx"
            it["y2"] = it["y1"]
        elif "dec" in names: it = dict(kind="range", y1=int(names["d0"]) * 10, y2=int(names["d0"]) * 10 + 9)
        elif "cent" in names:
            base = (int(names["cn"]) - 1) * 100
            lo, hi = SPAN[names["cq"].lower()] if names.get("cq") else (0, 99)
            it = dict(kind="range", y1=base + lo, y2=base + hi)
            if names.get("cq"): flag = "approx"
        elif "year" in names: it = dict(kind="year", y1=int(names["yy"]), y2=int(names["yy"]))
        if it and OK_YEAR(it["y1"]) and OK_YEAR(it["y2"]) and it["y1"] <= it["y2"]:
            it["flag"] = flag; out.append(it)
    return out


def _format(it):
    """(display, edtf, core_years, search_years) for one item"""
    f, y1, y2 = it["flag"], it["y1"], it["y2"]
    core = set(range(y1, y2 + 1)); pad = 5 if f else 0
    search = set(range(y1 - pad, y2 + pad + 1))
    if it["kind"] == "range":
        q = "?" if f else ""
        return f"between {y1} and {y2}{q}", f"{y1}{q}/{y2}{q}", core, search
    if it["kind"] == "year":
        if f == "approx": return f"approximately {y1}", f"{y1}~", core, search
        if f == "unc": return f"{y1}?", f"{y1}?", core, search
        return f"{y1}", f"{y1}", core, search
    mark = {"approx": "~", "unc": "?"}.get(f, "")
    if it["kind"] == "month":
        return f"{MONTHS[it['m'] - 1].capitalize()}, {y1}", f"{y1}-{it['m']:02d}{mark}", core, search
    return f"{MONTHS[it['m'] - 1].capitalize()} {it['d']}, {y1}", f"{y1}-{it['m']:02d}-{it['d']:02d}{mark}", core, search


def normalize(text):
    """free-text date -> dict(display, dates, edtf, status, note, core_years)"""
    empty = dict(display="", dates="", edtf="", status="unknown", note="", core_years=set())
    s = html.unescape(text or "").strip()
    if not s: return empty
    low = s.lower()
    if re.match(r"^\s*(unknown|undetermined|undated|n/a|none)\b", low):
        m = re.search(r"between\s+(\d{4})\s+and\s+(\d{4})", low)
        if m and UNCERTAIN.search(low):
            it = dict(kind="range", y1=int(m.group(1)), y2=int(m.group(2)), flag="unc")
            d, e, core, search = _format(it)
            return dict(display=d, dates=" ".join(map(str, sorted(search))), edtf=e, status="review",
                        note="started 'unknown'; used the stated range", core_years=core)
        return dict(empty, note="date unknown")
    items = []
    for n, seg in enumerate(re.split(r";", s)):
        lead = LEAD.sub("", seg, count=1)
        if not ITEM.match(re.sub(r"^\s*", "", lead)):
            if n == 0: return dict(empty, status="review", note="free-text narrative, no date at the start")
            continue                                  # later parts are commentary
        items += _items(seg)
    if not items: return dict(empty, status="review", note="no usable date found")
    parts = [_format(i) for i in items]
    core = set().union(*[p[2] for p in parts]); search = set().union(*[p[3] for p in parts])
    return dict(display="; ".join(p[0] for p in parts), dates=" ".join(map(str, sorted(search))),
                edtf=" ".join(p[1] for p in parts), status="ok" if len(items) == 1 else "multiple",
                note="" if len(items) == 1 else f"{len(items)} dates found", core_years=core)


# ---------------------------------------------------------------- command line
def gold_years(edtf):
    """years covered by a gold Date-EDTF value such as '1856 1870?/1874?'"""
    ys = set()
    for tok in (edtf or "").split():
        ends = [int(m.group(0)[:4]) for part in tok.split("/") for m in [re.match(r"\d{4}", part.strip("?~"))] if m]
        if len(ends) == 2: ys |= set(range(ends[0], ends[1] + 1))
        elif ends: ys.add(ends[0])
    return ys

def agreement(res, gold_edtf):
    """exact (same EDTF text) | same years | inside gold span | overlap | no overlap | no AI date | no gold date"""
    g = gold_years(gold_edtf); a = res["core_years"]
    if not g: return "no gold date"
    if not a: return "no AI date"
    if res["edtf"] == (gold_edtf or "").strip(): return "exact"
    if a == g: return "same years"
    if min(g) <= min(a) and max(a) <= max(g): return "inside gold span"
    if min(a) <= max(g) and min(g) <= max(a): return "overlap"
    return "no overlap"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="v3"); ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--check", action="store_true", help="compare with gold Date-EDTF (gold records only)")
    ap.add_argument("--include-holdout", action="store_true", help="also use the 10 holdout records (final evaluation only)")
    args = ap.parse_args()
    manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
    catalog = {r["CONTENTdm number"]: r for r in csv.DictReader(
        open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}
    rows = []
    for p in sorted(pathlib.Path("outputs", f"{args.prompt}_{args.model}").glob("[0-9]*.json"), key=lambda p: int(p.stem)):
        rec = json.loads(p.read_text(encoding="utf-8")); i = rec["id"]; m = manifest.get(i, {})
        if m.get("holdout") == "Y" and not args.include_holdout: continue
        if args.check and m.get("in_gold_set") != "Y": continue
        if not rec["valid"]: continue
        value = rec["output"]["date_estimate"]["value"]; res = normalize(value)
        row = {"id": i, "ai_value": value, "display": res["display"], "dates": res["dates"], "edtf": res["edtf"],
               "status": res["status"], "note": res["note"]}
        if args.check:
            row["gold_edtf"] = catalog[i]["Date-EDTF"]; row["agreement"] = agreement(res, catalog[i]["Date-EDTF"])
        rows.append(row)
    out = pathlib.Path(f"normalized_dates_{args.prompt}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    from collections import Counter
    print(f"wrote {out} ({len(rows)} records)")
    print("status:", dict(Counter(r["status"] for r in rows)))
    if args.check: print("agreement with gold Date-EDTF:", dict(Counter(r["agreement"] for r in rows)))
