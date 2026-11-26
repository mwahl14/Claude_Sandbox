"""Summarize the hand-rating sheets: mean 1-3 scores, error categories, reviewer minutes, and a small table for slides.
NO API calls; changes nothing in outputs/ except creating new rubric_rated.csv files when you ask (--prepare).

WHY A COPY:  score.py rewrites outputs/<run>/rubric.csv every time it runs, which would erase ratings typed into it.
             So rate in outputs/<run>/rubric_rated.csv (a copy made once by --prepare; --prepare never overwrites an existing copy).

STEPS
  1.  python3 rubric_summary.py --prepare          makes rubric_rated.csv for v1, v2.1 and v3 (30 DEV records each; add --include-holdout for all 40)
  2.  Open each rubric_rated.csv in Excel and fill, for each record:
        description_score_1to3 and alt_text_score_1to3  (1, 2 or 3; this script assumes 3 = best, 1 = weakest, as you defined your rubric)
        reviewer_minutes (minutes you spent on the record), error_category (one of: hallucination, misidentified place, anachronism,
        biased or outdated language, over-generic subject, shallow description, invalid heading, format failure, other), error_notes.
      Save as CSV (keep the same file name).  Blank cells are fine: they are counted as "not rated yet".
  3.  python3 rubric_summary.py                    prints the summary and writes rubric_summary.csv, rubric_errors.csv, rubric_summary.md
Options: --prompts v1,v2.1,v3   --model claude-sonnet-5-5   --file some.csv --label name   (summarize one specific file)
Dev (30) and holdout (10) rows are always reported separately.
"""
import argparse, csv, pathlib, sys
from collections import Counter

SCORE_LO, SCORE_HI = 1, 3

def num(text):
    try: return float(str(text).strip())
    except ValueError: return None

def summarize(rows, label=""):
    """rows from a rated rubric CSV -> list of dicts (one per subset) + list of warnings"""
    out, warnings = [], []
    for subset in sorted({r.get("subset", "") for r in rows}, key=lambda s: (s != "dev", s)):
        rs = [r for r in rows if r.get("subset", "") == subset]
        d = dict(run=label, subset=subset, records=len(rs))
        for key, col in (("desc", "description_score_1to3"), ("alt", "alt_text_score_1to3")):
            vals = []
            for r in rs:
                raw = str(r.get(col, "")).strip()
                if not raw: continue
                v = num(raw)
                if v is None or not (SCORE_LO <= v <= SCORE_HI):
                    warnings.append(f"{label} {subset} record {r.get('id')}: {col} = '{raw}' is not a number from {SCORE_LO} to {SCORE_HI} (ignored)")
                else: vals.append(v)
            d[f"{key}_rated"] = len(vals)
            d[f"{key}_mean"] = round(sum(vals) / len(vals), 2) if vals else ""
            d[f"{key}_dist"] = " ".join(f"{k}:{sum(1 for v in vals if v == k)}" for k in range(SCORE_LO, SCORE_HI + 1))
        mins = []
        for r in rs:
            raw = str(r.get("reviewer_minutes", "")).strip()
            if not raw: continue
            v = num(raw)
            if v is None or v < 0: warnings.append(f"{label} {subset} record {r.get('id')}: reviewer_minutes = '{raw}' is not a number (ignored)")
            else: mins.append(v)
        d["minutes_n"] = len(mins); d["minutes_total"] = round(sum(mins), 1)
        d["minutes_mean"] = round(sum(mins) / len(mins), 1) if mins else ""
        errs = Counter(str(r.get("error_category", "")).strip().lower() for r in rs if str(r.get("error_category", "")).strip())
        d["errors"] = dict(errs.most_common()); d["records_with_error"] = sum(errs.values())
        out.append(d)
    return out, warnings

def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))

def prepare(prompts, model, include_holdout):
    for p in prompts:
        run = pathlib.Path("outputs") / f"{p}_{model}"; src, dst = run / "rubric.csv", run / "rubric_rated.csv"
        if not src.exists(): print(f"skip {p}: {src} not found"); continue
        if dst.exists(): print(f"kept  {dst} (already exists; not overwritten)"); continue
        rows = [r for r in read_rows(src) if include_holdout or r["subset"] != "holdout"]
        with open(dst, "w", newline="", encoding="utf-8-sig") as f:       # utf-8-sig so Excel shows accents correctly
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        print(f"wrote {dst} ({len(rows)} records to rate)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default="v1,v2.1,v3"); ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--prepare", action="store_true"); ap.add_argument("--include-holdout", action="store_true")
    ap.add_argument("--file", default=""); ap.add_argument("--label", default="")
    args = ap.parse_args(); prompts = args.prompts.split(",")
    if args.prepare: return prepare(prompts, args.model, args.include_holdout)
    sources = [(args.label or pathlib.Path(args.file).stem, pathlib.Path(args.file))] if args.file else []
    if not sources:
        for p in prompts:
            run = pathlib.Path("outputs") / f"{p}_{args.model}"
            f = run / "rubric_rated.csv"
            if f.exists(): sources.append((p, f))
            else: print(f"{p}: no rubric_rated.csv yet (run  python3 rubric_summary.py --prepare  first)")
    summaries, warnings = [], []
    for label, path in sources:
        s, w = summarize(read_rows(path), label); summaries += s; warnings += w
    if not summaries: return print("nothing to summarize yet.")
    print(f"\n{'run':8s}{'subset':9s}{'records':>8s} | {'description':^26s} | {'alt text':^26s} | {'minutes':^28s} | errors")
    print(f"{'':25s} | {'rated  mean  1/2/3 counts':^26s} | {'rated  mean  1/2/3 counts':^26s} | {'rated  total   mean/record':^28s} |")
    for d in summaries:
        dist = lambda x: x.replace("1:", "").replace(" 2:", "/").replace(" 3:", "/")
        print(f"{d['run']:8s}{d['subset']:9s}{d['records']:8d} | {d['desc_rated']:3d}  {str(d['desc_mean']):>5s}  {dist(d['desc_dist']):>10s}    | "
              f"{d['alt_rated']:3d}  {str(d['alt_mean']):>5s}  {dist(d['alt_dist']):>10s}    | {d['minutes_n']:3d}  {d['minutes_total']:7.1f}  {str(d['minutes_mean']):>8s}       | "
              f"{d['records_with_error']} ({', '.join(f'{k} {v}' for k, v in d['errors'].items()) or '-'})")
        if d["desc_rated"] < d["records"] or d["alt_rated"] < d["records"]:
            print(f"{'':17s}not rated yet: {d['records'] - d['desc_rated']} descriptions, {d['records'] - d['alt_rated']} alt texts")
    flat = [{k: v for k, v in d.items() if k != "errors"} for d in summaries]
    with open("rubric_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(flat[0])); w.writeheader(); w.writerows(flat)
    with open("rubric_errors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["run", "subset", "error_category", "records"])
        for d in summaries:
            for k, v in d["errors"].items(): w.writerow([d["run"], d["subset"], k, v])
    with open("rubric_summary.md", "w", encoding="utf-8") as f:
        f.write("| Prompt | Records | Description (mean of 3) | Alt text (mean of 3) | Minutes per record | Records with an error |\n|---|---|---|---|---|---|\n")
        for d in summaries:
            f.write(f"| {d['run']} ({d['subset']}) | {d['records']} | {d['desc_mean'] or 'not rated'} (n={d['desc_rated']}) | {d['alt_mean'] or 'not rated'} (n={d['alt_rated']}) | "
                    f"{d['minutes_mean'] if d['minutes_mean'] != '' else 'not logged'} | {d['records_with_error']} |\n")
    print("\nwrote rubric_summary.csv, rubric_errors.csv, rubric_summary.md")
    for w_ in warnings: print("WARNING:", w_)

if __name__ == "__main__":
    main()
