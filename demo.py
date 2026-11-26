"""3-minute demo: ONE photograph from image to Dublin Core, using the saved AI output (no API call, works offline).
Run it from the project folder in a fresh terminal:

    python3 demo.py                      shows steps 1-4 (image, AI output, validation + flags, review sheet) and stops so you can
                                         review in Excel; it then prints the one command that does the export.
    python3 demo.py --simulate           also plays the cataloger (accepts, rejects flagged terms, edits the place) and runs the export:
                                         the whole pipeline in one command. Good for the recorded backup.
Options:  --id 220  (record to show, default 220)   --prompt v3   --pause (wait for Enter between steps, for recording)
          --no-open (do not open the image / spreadsheet)
Writes only demo_review.xlsx and demo_dc_export.csv in this folder. Nothing in outputs/ or the catalog is touched.
"""
import argparse, csv, json, pathlib, subprocess, sys, textwrap
from openpyxl import load_workbook
from normalize_dates import normalize
from term_flags import term_flag

ap = argparse.ArgumentParser()
ap.add_argument("--id", default="220"); ap.add_argument("--prompt", default="v3"); ap.add_argument("--model", default="claude-sonnet-5-5")
ap.add_argument("--simulate", action="store_true"); ap.add_argument("--pause", action="store_true"); ap.add_argument("--no-open", action="store_true")
args = ap.parse_args()
run = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
rec = json.loads((run / f"{args.id}.json").read_text(encoding="utf-8")); o = rec["output"]; prov = rec["provenance"]
SHEET, EXPORT = "demo_review.xlsx", "demo_dc_export.csv"

def step(n, title):
    if args.pause and n > 1: input("\n   [press Enter to continue] ")
    print(f"\n{'=' * 78}\nSTEP {n}: {title}\n{'=' * 78}")
def wrap(text, indent="   "): print(textwrap.fill(text, 100, initial_indent=indent, subsequent_indent=indent))
def open_file(path):
    if not args.no_open and sys.platform == "darwin": subprocess.run(["open", path])

# ---- 1 image
step(1, "THE PHOTOGRAPH (the only thing the model sees, plus our vocabulary lists)")
print(f"   images/{args.id}.jpg   (an album page from the Prosch Albums)")
print("   Not sent to the model: the catalog title, notes, or subjects. Those are the answer key we score against.")
open_file(f"images/{args.id}.jpg")

# ---- 2 AI output
step(2, f"THE AI OUTPUT  (model {prov['model']}, prompt {prov['prompt_version']}, {prov['date']}, "
        f"{prov['input_tokens']:,} tokens in / {prov['output_tokens']:,} out)")
print("   title_suggestion:"); wrap(o["title_suggestion"], "      ")
print("   alt_text:"); wrap(o["alt_text"], "      ")
print("   description:"); wrap(o["description"], "      ")
print("   subjects (chosen only from the supplied lists):")
for kind, key in (("LCSH ", "subjects_lcsh"), ("TGM  ", "genre_tgm")):
    for t in o[key]: print(f"      {kind} [{t['confidence']:6s}] {t['term']}")
print("   places:  " + "; ".join(f"{p['place']} ({p['basis']})" for p in o["depicted_places"]))
print(f"   date:    {o['date_estimate']['value']}  (confidence {o['date_estimate']['confidence']})")

# ---- 3 validation
step(3, "VALIDATION: check headings against id.loc.gov, flag terms for the reviewer, normalize the date")
val = {r["id"]: r for r in csv.DictReader(open(run / "validation.csv", encoding="utf-8"))}.get(args.id, {})
n_flag = 0
for kind, key in (("lcsh", "subjects_lcsh"), ("tgm", "genre_tgm")):
    for t in o[key]:
        fl, why, st = term_flag(kind, t["term"], t["confidence"]); n_flag += fl
        print(f"   {'FLAG ' if fl else 'ok   '} {st:10s} {t['term'][:62]:62s} {why}")
print(f"   {n_flag} of {len(o['subjects_lcsh']) + len(o['genre_tgm'])} subject terms flagged: review those first. "
      f"(In our tests flagged terms matched the catalogers about half as often.)")
if val: print(f"   record tier today: {val['tier']} (score {val['confidence']}). We do not claim this ranks records; the term flags are the useful signal.")
nd = normalize(o["date_estimate"]["value"])
print(f"   date normalized ->  display: {nd['display'] or '(needs a cataloger)'}   EDTF: {nd['edtf'] or '-'}   search years: {nd['dates'][:40] or '-'}")

# ---- 4 review sheet
step(4, "THE REVIEW SHEET: a cataloger accepts, edits or rejects every AI value")
out = subprocess.run([sys.executable, "make_review_sheet.py", "--prompt", args.prompt, "--ids", args.id, "--out", SHEET], capture_output=True, text=True)
if out.returncode: sys.exit(out.stderr)
print("   " + out.stdout.splitlines()[0]); print("   columns to fill: decision (accept / edit / reject), edited_value, error_category, reviewer_notes, reviewer_minutes")
open_file(SHEET)
if args.simulate:
    wb = load_workbook(SHEET); ws = wb["Review"]; col = {c.value: i + 1 for i, c in enumerate(ws[1])}
    print("   (--simulate) playing the cataloger: accept everything, reject flagged subject terms, trim the hedge in the place, log 4.5 minutes")
    first = True
    for r in range(2, ws.max_row + 1):
        get = lambda name: ws.cell(r, col[name]).value
        put = lambda name, v: ws.cell(r, col[name], v)
        if get("review_flag") == "Y":
            term = str(get("ai_value")); place = term.split("--")[-1] if term.count("--") >= 2 else ""
            wrong_place = bool(place) and place.lower() not in " ".join(p["place"] for p in o["depicted_places"]).lower()
            put("decision", "reject"); put("error_category", "misidentified place" if wrong_place else "other")   # e.g. Barns--...--Tacoma for a Seattle photo
        elif get("field") == "place" and " (" in str(get("ai_value")): put("decision", "edit"); put("edited_value", str(get("ai_value")).split(" (")[0])
        else: put("decision", "accept")
        if first: put("reviewer_minutes", 4.5); first = False
    wb.save(SHEET)

# ---- 5 export
step(5, "EXPORT: accepted and edited values become Dublin Core, with provenance kept")
if not args.simulate:
    print(f"   Review the sheet in Excel (or run with --simulate), save it, then run:\n\n       python3 export_dc.py {SHEET} --out {EXPORT}\n")
else:
    out = subprocess.run([sys.executable, "export_dc.py", SHEET, "--out", EXPORT], capture_output=True, text=True)
    if out.returncode: sys.exit(out.stderr)
    print("   " + "\n   ".join(out.stdout.strip().splitlines()))
    row = next(csv.DictReader(open(EXPORT, encoding="utf-8-sig")))
    print()
    for k, v in row.items():
        if v and k.endswith("_provenance") is False and not k.startswith("ai_"):
            prov_ = row.get(k + "_provenance", "")
            print(f"   {k:20s} {(v[:70] + '...') if len(v) > 70 else v:75s} {('<- ' + prov_[:40]) if prov_ else ''}")
    print(f"\n   AI-derived values stay labelled (ai-accepted / ai-edited); model {row['ai_model']}, prompt {row['ai_prompt_version']}, run {row['ai_run_date']}.")
    print("   Nothing is written back to the catalog: the export is a new file for the cataloger to load or compare.")
print("\nDone.")
