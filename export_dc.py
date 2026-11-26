"""Read a COMPLETED review sheet and write a Dublin Core CSV. NO API calls.
It never writes to Prosch_Export.txt or any catalog record; it only creates new CSV files next to the sheet.

Usage:  python3 export_dc.py review_v3.xlsx                      (writes dc_export_v3.csv)
        python3 export_dc.py review_v3.xlsx --mapping dc_mapping.csv --out my_export.csv

What goes in:  rows marked accept (the AI value) and edit (your edited_value).  Rows marked reject, or left blank, are dropped.
The mapping from review fields to Dublin Core elements comes from dc_mapping.csv, so it can change when the dictionary is approved
(change an element name there, or delete a row to leave that field out). Several fields mapped to one element are joined with ' ; '.

AI-generated values stay distinguishable: every element column has a companion '<element>_provenance' column with one entry per
value ('ai-accepted' or 'ai-edited', in the same order), and each record row carries ai_model, ai_prompt_version, ai_run_date,
review_status (reviewed / partial) and reviewer_minutes. A date you edit is re-read by normalize_dates.py so that the display date,
the hidden search years and the EDTF value stay consistent; if it cannot be read, the display text is kept and the other two are left blank.
If any row has an error_category, a second file '<out>_errors.csv' lists those rows for the error log.
"""
import argparse, csv, json, pathlib
from collections import Counter, OrderedDict
from openpyxl import load_workbook
from normalize_dates import normalize

ap = argparse.ArgumentParser()
ap.add_argument("sheet"); ap.add_argument("--mapping", default="dc_mapping.csv"); ap.add_argument("--out", default="")
args = ap.parse_args()
sheet = pathlib.Path(args.sheet)
out = pathlib.Path(args.out) if args.out else sheet.with_name("dc_export_" + sheet.stem.replace("review_", "") + ".csv")

mapping = OrderedDict((r["source_field"], r["dublin_core_element"].strip()) for r in csv.DictReader(open(args.mapping, encoding="utf-8")) if r["dublin_core_element"].strip())
elements = list(OrderedDict.fromkeys(mapping.values()))

ws = load_workbook(sheet, data_only=True)["Review"]
header = [c.value for c in ws[1]]
rows = [dict(zip(header, [("" if v is None else v) for v in r])) for r in ws.iter_rows(min_row=2, values_only=True) if any(v not in (None, "") for v in r)]

records = OrderedDict(); problems = []; counts = Counter(); unmapped = Counter(); errlog = []
for r in rows:
    rid = str(r["record_id"]); rec = records.setdefault(rid, dict(values={}, pending=0, minutes=0.0, model="", prompt="", date=""))
    rec["model"], rec["prompt"], rec["date"] = r["model"], r["prompt_version"], r["run_date"]
    try: rec["minutes"] += float(r["reviewer_minutes"] or 0)
    except ValueError: problems.append(f"record {rid} row {r['row_key']}: reviewer_minutes '{r['reviewer_minutes']}' is not a number (ignored)")
    if r["error_category"]: errlog.append({k: r[k] for k in ("record_id", "field", "ai_value", "decision", "edited_value", "error_category", "reviewer_notes")})
    decision = str(r["decision"]).strip().lower()
    if decision == "":
        rec["pending"] += 1; counts["pending"] += 1; continue
    if decision not in ("accept", "edit", "reject"):
        problems.append(f"record {rid} row {r['row_key']}: decision '{r['decision']}' is not accept / edit / reject (row skipped)"); rec["pending"] += 1; continue
    counts[decision] += 1
    if decision == "reject": continue
    value = str(r["edited_value"]).strip() if decision == "edit" else str(r["ai_value"]).strip()
    if not value:
        problems.append(f"record {rid} row {r['row_key']}: marked {decision} but there is no value (row skipped)"); continue
    prov = "ai-accepted" if decision == "accept" else "ai-edited"
    produced = []                                     # (source_field, value) pairs this row contributes
    if r["field"] == "date":
        if decision == "accept":
            aux = json.loads(r["aux"]) if r["aux"] else {}
            produced = [("date_display", value), ("date_search", aux.get("dates", "")), ("date_edtf", aux.get("edtf", ""))]
        else:
            n = normalize(value)
            if n["status"] in ("ok", "multiple"): produced = [("date_display", n["display"]), ("date_search", n["dates"]), ("date_edtf", n["edtf"])]
            else:
                produced = [("date_display", value)]
                problems.append(f"record {rid}: edited date '{value}' could not be read; display date kept, search years and EDTF left blank")
    else:
        produced = [(r["field"], value)]
    for src, v in produced:
        if not v: continue
        if src not in mapping: unmapped[src] += 1; continue
        rec["values"].setdefault(mapping[src], []).append((v, prov))

fields = ["record_id"] + [x for e in elements for x in (e, e + "_provenance")] + ["ai_model", "ai_prompt_version", "ai_run_date", "review_status", "reviewer_minutes"]
exported = 0
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
    for rid, rec in records.items():
        if not rec["values"]: continue
        row = {"record_id": rid, "ai_model": rec["model"], "ai_prompt_version": rec["prompt"], "ai_run_date": rec["date"],
               "review_status": "reviewed" if rec["pending"] == 0 else "partial", "reviewer_minutes": round(rec["minutes"], 1)}
        for e in elements:
            seen = []
            for v, p in rec["values"].get(e, []):
                if (v, p) not in seen: seen.append((v, p))
            row[e] = " ; ".join(v for v, _ in seen); row[e + "_provenance"] = " ; ".join(p for _, p in seen)
        w.writerow(row); exported += 1
if errlog:
    ep = out.with_name(out.stem + "_errors.csv")
    with open(ep, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(errlog[0])); w.writeheader(); w.writerows(errlog)
print(f"wrote {out}: {exported} of {len(records)} records had at least one accepted or edited value")
print("rows:", {k: counts[k] for k in ("accept", "edit", "reject", "pending")})
if unmapped: print("not exported (no row in the mapping):", dict(unmapped))
if errlog: print(f"wrote {ep} ({len(errlog)} rows with an error category)")
if any(rec["pending"] for rec in records.values()): print("note: records with unreviewed (blank) rows are marked review_status = partial")
for p in problems: print("WARNING:", p)
