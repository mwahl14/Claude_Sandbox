"""Step 2: download a JPEG (max 1000 px wide) for each record in manifest.csv.
Usage:  python3 download_images.py --test      (first 3 only)
        python3 download_images.py            (all; safe to re-run)
Uses the library's public IIIF image service.
"""
import csv, sys, time, pathlib, urllib.request

BASE = "https://digitalcollections.lib.washington.edu/iiif/2/prosch_washington:{id}/full/!1000,1000/0/default.jpg"
OUT = pathlib.Path("images"); OUT.mkdir(exist_ok=True)

ids = [r["id"] for r in csv.DictReader(open("manifest.csv", encoding="utf-8"))]
if "--test" in sys.argv: ids = ids[:3]

failed = []
for n, i in enumerate(ids, 1):
    dest = OUT / f"{i}.jpg"
    if dest.exists(): continue                  # skip what we already have
    req = urllib.request.Request(BASE.format(id=i), headers={"User-Agent": "prosch-metadata-study/0.1"})
    for attempt in range(1, 5):                 # up to 4 tries per image
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                dest.write_bytes(resp.read())
            print(f"[{n}/{len(ids)}] saved {dest}")
            break
        except OSError as e:                    # covers resets, timeouts, HTTP errors
            print(f"[{n}/{len(ids)}] {i} attempt {attempt} failed: {e}")
            time.sleep(3 * attempt)             # wait longer each retry
    else:
        failed.append(i)
    time.sleep(1.5)                             # be polite to the server

print("done;", len(failed), "failed", failed)
