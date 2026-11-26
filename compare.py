"""Step 4: build review.html showing each image, the AI output, and the catalog record side by side.
Usage:  python3 compare.py                      (uses prompt v1 / default model)
        python3 compare.py --prompt v2 --model claude-sonnet-5-5
Then open review.html in a browser. Needs Prosch_Export.txt, manifest.csv, images/ and outputs/ in the folder.
"""
import argparse, csv, html, json, pathlib

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", default="v1")
ap.add_argument("--model", default="claude-sonnet-5-5")
args = ap.parse_args()
out_dir = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"

catalog = {r["CONTENTdm number"]: r for r in csv.DictReader(
    open("Prosch_Export.txt", encoding="utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE)}
e = lambda s: html.escape(str(s or ""))

def terms(items, key):
    return "; ".join(f"{e(i[key])} <small>({e(i.get('confidence',''))})</small>" for i in items) or "—"

def ai_block(o):
    d = o["date_estimate"]; f = o["uncertainty_flag"]
    people = "; ".join(e(p["description"]) + (f" [name from {e(p['name_source'])}]" if p["name_source"] != "none" else "")
                       for p in o["depicted_people"]) or "—"
    places = "; ".join(f"{e(p['place'])} <small>({e(p['basis'])}, {e(p['confidence'])})</small>" for p in o["depicted_places"]) or "—"
    return f"""<p><b>Title:</b> {e(o['title_suggestion'])}</p>
<p><b>Description:</b> {e(o['description'])}</p>
<p><b>Alt text:</b> {e(o['alt_text'])}</p>
<p><b>LCSH:</b> {terms(o['subjects_lcsh'], 'term')}</p>
<p><b>TGM:</b> {terms(o['genre_tgm'], 'term')}</p>
<p><b>People:</b> {people}</p>
<p><b>Places:</b> {places}</p>
<p><b>Date:</b> {e(d['value'])} <small>({e(d['basis'])}; {e(d['confidence'])})</small></p>
<p><b>Visible text:</b> {e(o['visible_text']) or '—'}</p>
<p><b>Flag:</b> {'REVIEW' if f['needs_review'] else 'ok'} {e('; '.join(f['reasons']))}</p>"""

cards = []
for p in sorted(out_dir.glob("*.json")):
    rec = json.loads(p.read_text(encoding="utf-8")); i = rec["id"]; c = catalog.get(i, {})
    if rec["valid"]:
        ai = ai_block(rec["output"])
    else:
        ai = f"<p class=bad><b>INVALID OUTPUT</b>: {e(rec.get('error'))}</p><pre>{e(rec['raw'])}</pre>"
    cat = f"""<p><b>Title:</b> {e(c.get('Title'))}</p>
<p><b>Date:</b> {e(c.get('Date'))} ({e(c.get('Date-EDTF'))})</p>
<p><b>Notes (captions):</b> {e(c.get('Notes'))}</p>
<p><b>LCSH:</b> {e(c.get('Subjects (LCSH)'))}</p>
<p><b>LCTGM:</b> {e(c.get('Subjects (LCTGM)'))}</p>
<p><b>Location:</b> {e(c.get('Location Depicted'))}</p>"""
    pv = rec["provenance"]
    cards.append(f"""<section><h2>Record {e(i)} <small>{e(c.get('Order Number'))} · {e(pv['model'])} · prompt {e(pv['prompt_version'])} · {e(pv['date'])}</small></h2>
<div class=row><div class=img><img src="images/{e(i)}.jpg"></div>
<div class=col><h3>AI output</h3>{ai}</div><div class=col><h3>Catalog record</h3>{cat}</div></div></section>""")

page = f"""<!doctype html><meta charset=utf-8><title>Prosch review: {e(args.prompt)}</title>
<style>body{{font:14px/1.45 system-ui,sans-serif;margin:20px;max-width:1500px}}section{{border-top:2px solid #999;padding:10px 0}}
.row{{display:flex;gap:20px;align-items:flex-start}}.img{{flex:0 0 340px}}.img img{{width:100%}}.col{{flex:1;min-width:0}}
h2{{font-size:16px}}h3{{font-size:14px;margin:0 0 6px;color:#555}}p{{margin:4px 0}}small{{color:#666}}.bad{{color:#b00}}pre{{white-space:pre-wrap}}</style>
<h1>Prosch review — prompt {e(args.prompt)}, {e(args.model)} ({len(cards)} records)</h1>{''.join(cards)}"""
pathlib.Path("review.html").write_text(page, encoding="utf-8")
print("wrote review.html with", len(cards), "records")
