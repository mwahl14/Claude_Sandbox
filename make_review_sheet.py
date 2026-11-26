"""Build the Excel REVIEW SHEET: one row per record per AI field, for a cataloger to accept / edit / reject.
NO API calls. Reads the AI output files and writes a new .xlsx; it never changes outputs/ or the catalog.

Usage:  python3 make_review_sheet.py --prompt v3                     (all valid DEV gold records -> review_v3.xlsx)
        python3 make_review_sheet.py --prompt v3 --ids 213,220,25    (only these records)
        python3 make_review_sheet.py --prompt v3 --out my_sheet.xlsx
The 10 holdout records are left out unless you pass --include-holdout.

In the sheet the reviewer fills: decision (accept / edit / reject), edited_value (when editing), error_category,
reviewer_notes, reviewer_minutes. Rows are sorted so low-confidence records (full review) come first.
Then run  python3 export_dc.py <sheet>.xlsx  to make the Dublin Core CSV.
"""
import argparse, csv, json, pathlib
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from normalize_dates import normalize
from term_flags import term_flag

DECISIONS = ["accept", "edit", "reject"]
ERRORS = ["hallucination", "misidentified place", "anachronism", "biased or outdated language", "over-generic subject",
          "shallow description", "invalid heading", "format failure", "other"]
TIER_ORDER = {"full review": 0, "sample review": 1, "sample-check": 2}
FIELD_ORDER = {"title": 0, "description": 1, "alt_text": 2, "date": 3, "place": 4, "subject_lcsh": 5, "subject_tgm": 6}
COLUMNS = ["record_id", "tier", "field", "ai_value", "ai_confidence", "vocab_list", "review_flag", "flag_reason", "ai_note", "decision", "edited_value",
           "error_category", "reviewer_notes", "reviewer_minutes", "image", "model", "prompt_version", "run_date", "row_key", "aux"]
WIDTH = {"record_id": 9, "tier": 14, "field": 14, "ai_value": 60, "ai_confidence": 11, "vocab_list": 11, "review_flag": 9, "flag_reason": 30, "ai_note": 40,
         "decision": 10, "edited_value": 45, "error_category": 24, "reviewer_notes": 30, "reviewer_minutes": 10, "image": 14,
         "model": 18, "prompt_version": 10, "run_date": 11, "row_key": 22, "aux": 8}
FILL = {"full review": "F8D7DA", "sample review": "FFF3CD", "sample-check": "E2F0D9"}   # light red / yellow / green

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v3"); ap.add_argument("--model", default="claude-sonnet-5-5")
ap.add_argument("--ids", default=""); ap.add_argument("--out", default="")
ap.add_argument("--include-holdout", action="store_true")
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
out = pathlib.Path(args.out or f"review_{args.prompt}.xlsx")

manifest = {r["id"]: r for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))}
tiers = {r["id"]: r["tier"] for r in csv.DictReader(open(run / "validation.csv", encoding="utf-8"))} if (run / "validation.csv").exists() else {}
vocab = {r["term"]: r["class"] for r in csv.DictReader(open("vocab_classification.csv", encoding="utf-8"))} if pathlib.Path("vocab_classification.csv").exists() else {}
want = {x.strip() for x in args.ids.split(",") if x.strip()}

rows = []
for p in sorted(run.glob("[0-9]*.json"), key=lambda p: int(p.stem)):
    rec = json.loads(p.read_text(encoding="utf-8")); i = rec["id"]; m = manifest.get(i, {})
    if want and i not in want: continue
    if not want and m.get("in_gold_set") != "Y": continue            # default: gold records only
    if m.get("holdout") == "Y" and not args.include_holdout: continue
    if not rec["valid"]: continue
    o, prov = rec["output"], rec["provenance"]; tier = tiers.get(i, "not validated")
    base = dict(record_id=int(i), tier=tier, image=f"images/{i}.jpg", model=prov["model"],
                prompt_version=prov["prompt_version"], run_date=prov["date"])
    def add(field, n, value, conf="", vlist="", note="", aux="", flag="", why=""):
        rows.append(dict(base, field=field, ai_value=value, ai_confidence=conf, vocab_list=vlist, ai_note=note,
                         review_flag=flag, flag_reason=why, row_key=f"{i}|{field}|{n}", aux=aux))
    fc = o.get("field_confidence", {})
    add("title", 1, o["title_suggestion"], fc.get("title", ""))
    add("description", 1, o["description"], fc.get("description", ""))
    add("alt_text", 1, o["alt_text"])
    d = o["date_estimate"]; nd = normalize(d["value"])
    if nd["display"]:
        add("date", 1, nd["display"], d.get("confidence", ""), "", f"AI wrote: {d['value']}  |  basis: {d.get('basis', '')}",
            json.dumps({"dates": nd["dates"], "edtf": nd["edtf"]}))
    else:
        add("date", 1, "", d.get("confidence", ""), "", f"Could not normalize. AI wrote: {d['value']}  |  Enter a date in edited_value, or reject.")
    for n, pl in enumerate(o["depicted_places"], 1):
        add("place", n, pl["place"], pl["confidence"], "", f"basis: {pl['basis']}")
    for n, t in enumerate(o["subjects_lcsh"], 1):
        fl, why, _ = term_flag("lcsh", t["term"], t["confidence"])
        add("subject_lcsh", n, t["term"], t["confidence"], vocab.get(t["term"], "not in lists"), flag="Y" if fl else "", why=why)
    for n, t in enumerate(o["genre_tgm"], 1):
        fl, why, _ = term_flag("tgm", t["term"], t["confidence"])
        add("subject_tgm", n, t["term"], t["confidence"], vocab.get(t["term"], "not in lists"), flag="Y" if fl else "", why=why)

rows.sort(key=lambda r: (TIER_ORDER.get(r["tier"], 3), r["record_id"], FIELD_ORDER[r["field"]], 0 if r["review_flag"] == "Y" else 1, r["row_key"]))

wb = Workbook(); ws = wb.active; ws.title = "Review"
ws.append(COLUMNS)
for r in rows: ws.append([r.get(c, "") for c in COLUMNS])
for c in ws[1]: c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="44546A")
for col, name in enumerate(COLUMNS, 1):
    ws.column_dimensions[ws.cell(1, col).column_letter].width = WIDTH[name]
wrap = Alignment(wrap_text=True, vertical="top")
for row in ws.iter_rows(min_row=2):
    for c in row: c.alignment = wrap
    row[1].fill = PatternFill("solid", fgColor=FILL.get(row[1].value, "FFFFFF"))
    fl = row[COLUMNS.index("review_flag")]
    if fl.value == "Y": fl.fill = PatternFill("solid", fgColor="F4B183"); fl.font = Font(bold=True)
    img = row[COLUMNS.index("image")]; img.hyperlink = str(pathlib.Path(img.value).resolve()); img.font = Font(color="0563C1", underline="single")
ws.freeze_panes = "D2"; ws.auto_filter.ref = ws.dimensions
ws.column_dimensions["aux"].hidden = True
last = max(len(rows) + 1, 2)
lists = wb.create_sheet("Lists")
lists.append(["decision"] + [""] * 0); [lists.append([d]) for d in DECISIONS]
lists["B1"] = "error_category"
for n, e in enumerate(ERRORS, 2): lists.cell(n, 2, e)
dv1 = DataValidation(type="list", formula1=f"=Lists!$A$2:$A${len(DECISIONS) + 1}", allow_blank=True, showErrorMessage=True)
dv2 = DataValidation(type="list", formula1=f"=Lists!$B$2:$B${len(ERRORS) + 1}", allow_blank=True, showErrorMessage=True)
dv1.add(f"{ws.cell(1, COLUMNS.index('decision') + 1).column_letter}2:{ws.cell(1, COLUMNS.index('decision') + 1).column_letter}{last}")
dv2.add(f"{ws.cell(1, COLUMNS.index('error_category') + 1).column_letter}2:{ws.cell(1, COLUMNS.index('error_category') + 1).column_letter}{last}")
ws.add_data_validation(dv1); ws.add_data_validation(dv2)

readme = wb.create_sheet("README", 0)
for line in ["REVIEW SHEET (AI-suggested metadata, for cataloger review)", "",
             f"Prompt {args.prompt}, model {args.model}. Every row is one AI-suggested value. Nothing here is catalog data until you accept it.", "",
             "For each row, fill in the 'decision' column (dropdown):",
             "  accept = keep the AI value as it is",
             "  edit   = type your corrected value in 'edited_value' (a corrected date is re-read by the export, e.g. 'circa 1885' or 'between 1880 and 1889')",
             "  reject = drop it; it will not be exported",
             "Leave 'decision' blank for rows you have not reviewed yet. Blank rows are NOT exported.", "",
             "Also useful: error_category (dropdown) when something is wrong, reviewer_notes, and reviewer_minutes",
             "(enter the minutes for a record on any one of its rows; the export adds them up per record).", "",
             "Tier colors: red = full review (check every row), yellow = sample review, green = sample-check.",
             "vocab_list shows where a subject term came from: lcsh / tgm / local (no LC authority record) / not in lists.",
             "review_flag = Y (orange) marks a subject term to look at first, and flag_reason says why: the model rated it 'low' confidence,",
             "or its heading was not found at id.loc.gov / is only a variant. In our dev tests flagged terms matched the catalogers' subjects about half as often",
             "as unflagged ones. A blank flag does NOT mean the term is right: check every row. Within each record, flagged subject rows are listed first.",
             "To work through flagged terms only, use the filter arrow on the review_flag column.",
             "Click the 'image' cell to open the photograph. Do not change the record_id, field, or row_key columns.", "",
             "When finished, save the file and run:  python3 export_dc.py " + out.name]:
    readme.append([line])
readme.column_dimensions["A"].width = 120; readme["A1"].font = Font(bold=True, size=13)
wb.save(out)
from collections import Counter
print(f"wrote {out}: {len(rows)} rows, {len({r['record_id'] for r in rows})} records")
print("rows by field:", dict(Counter(r["field"] for r in rows)))
print("subject terms flagged for review:", sum(r["review_flag"] == "Y" for r in rows), "of", sum(r["field"].startswith("subject") for r in rows))
print("records by tier:", dict(Counter({r['record_id']: r['tier'] for r in rows}.values())))
