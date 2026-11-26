"""Step 3: send images to a vision model and save structured JSON.
Usage:  python3 describe.py --n 10                          (prompt v1)
        python3 describe.py --n 130 --prompt v2.1           (uses vocab_lcsh.txt / vocab_tgm.txt / vocab_local.txt)
        python3 describe.py --n 10 --prompt v2.1 --model claude-sonnet-5-5
Needs the ANTHROPIC_API_KEY environment variable.
Only the IMAGE (plus the prompt's vocabulary lists) is sent; catalog notes are never sent.
Safe to re-run: images that already have an output file are skipped.
"""
import argparse, base64, csv, datetime, io, json, pathlib
import anthropic, jsonschema
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--prompt", default="v1")
ap.add_argument("--model", default="claude-sonnet-5-5")
ap.add_argument("--only", choices=["dev-gold", "holdout"], default=None,
                help="dev-gold = in_gold_set = Y and holdout = N; holdout = holdout = Y (run once, at the end)")
args = ap.parse_args()

def read(path): return pathlib.Path(path).read_text(encoding="utf-8")

prompt_text = read(f"prompts/{args.prompt}.txt")
for tag, fname in (("{VOCAB_LCSH}", "vocab_lcsh.txt"), ("{VOCAB_TGM}", "vocab_tgm.txt"),
                   ("{VOCAB_LOCAL}", "vocab_local.txt"), ("{CONTEXT}", "context.txt")):
    if tag in prompt_text:
        base = pathlib.Path(fname)
        versioned = base.with_name(f"{base.stem}_{args.prompt}{base.suffix}")   # e.g. vocab_tgm_v3.txt
        p = versioned if versioned.exists() else base
        if not p.exists() and tag != "{CONTEXT}":
            raise SystemExit(f"Missing {fname}. Run build_vocab.py first.")
        prompt_text = prompt_text.replace(tag, read(p).strip() if p.exists() else "")
schema = json.loads(read("schema.json"))
out_dir = pathlib.Path("outputs") / f"{args.prompt}_{args.model}"
out_dir.mkdir(parents=True, exist_ok=True)

client = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY from the environment

def load_image_b64(path):
    """Re-encode as JPEG, at most 1000 px on the long side."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((1000, 1000))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=90)
    return base64.standard_b64encode(buf.getvalue()).decode()

def parse_json(text):
    """Take everything from the first { to the last }, ignoring words or code fences around it."""
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])

rows = list(csv.DictReader(open("manifest.csv", encoding="utf-8")))
if args.only == "dev-gold":
    rows = [r for r in rows if r["in_gold_set"] == "Y" and r["holdout"].strip().upper() != "Y"]
elif args.only == "holdout":
    rows = [r for r in rows if r["holdout"].strip().upper() == "Y"]
done = 0
for r in rows:
    if done >= args.n: break
    if r["rights_cleared"].strip().upper() == "N":
        print(f"skip {r['id']} (rights_cleared = N)"); continue
    img_path = pathlib.Path("images") / f"{r['id']}.jpg"
    dest = out_dir / f"{r['id']}.json"
    if dest.exists(): done += 1; continue
    if not img_path.exists():
        print(f"missing image {img_path}"); continue

    resp = client.messages.create(
        model=args.model, max_tokens=4000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": load_image_b64(img_path)}},
            {"type": "text", "text": prompt_text}]}])
    raw = "".join(b.text for b in resp.content if b.type == "text")
    record = {"id": r["id"], "raw": raw}
    try:
        data = parse_json(raw)
        jsonschema.validate(data, schema)
        record["output"] = data; record["valid"] = True
    except Exception as e:
        record["valid"] = False; record["error"] = str(e)[:300]
    record["provenance"] = {"model": args.model, "prompt_version": args.prompt,
        "date": datetime.date.today().isoformat(),
        "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
        "stop_reason": resp.stop_reason}
    dest.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    done += 1
    print(f"[{done}/{args.n}] {r['id']} valid={record['valid']} ({resp.stop_reason})")

print("finished; results in", out_dir)
