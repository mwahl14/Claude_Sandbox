"""Step 1: choose a stratified sample of Prosch records and write manifest.csv."""
import csv, random, re, collections
random.seed(42)  # fixed seed so the sample is reproducible

rows = list(csv.DictReader(open("Prosch_Export.txt", encoding="utf-8", errors="replace"),
                           delimiter="\t", quoting=csv.QUOTE_NONE))

def decade(r):
    m = re.match(r"(\d{3})", r["Date-EDTF"] or "")
    return (m.group(1) + "0s") if m else "undated"

# Eligible: has an image (not the .cpd wrapper) and a CONTENTdm id
elig = [r for r in rows if not r["CONTENTdm file name"].lower().endswith(".cpd")]

# Gold candidates: complete cataloger metadata
def is_gold_candidate(r):
    return all((r[k] or "").strip() for k in
               ["Title", "Date-EDTF", "Notes", "Subjects (LCTGM)", "Subjects (LCSH)", "Location Depicted"])

def stratified(pool, n):
    """Pick n records spread across (collection, decade) strata."""
    groups = collections.defaultdict(list)
    for r in pool:
        groups[(r["Digital Collection"], decade(r))].append(r)
    for g in groups.values(): random.shuffle(g)
    picked = []
    while len(picked) < n and any(groups.values()):
        for k in sorted(groups):
            if groups[k] and len(picked) < n:
                picked.append(groups[k].pop())
    return picked

gold = stratified([r for r in elig if is_gold_candidate(r)], 40)
gold_ids = {r["CONTENTdm number"] for r in gold}
rest = [r for r in elig if r["CONTENTdm number"] not in gold_ids]
other = stratified(rest, 90)

# Hold out 10 of the gold set; never tune prompts on these
holdout_ids = {r["CONTENTdm number"] for r in random.sample(gold, 10)}

out = []
for r in gold + other:
    i = r["CONTENTdm number"]
    out.append({
        "id": i,
        "order_number": r["Order Number"],
        "collection": r["Digital Collection"],
        "decade": decade(r),
        "title": r["Title"],
        "in_gold_set": "Y" if i in gold_ids else "N",
        "holdout": "Y" if i in holdout_ids else "N",
        "rights_uri": r["Rights URI"],
        "rights_cleared": "",   # YOU fill in
        "notes_for_sample": "",
    })

with open("manifest.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader(); w.writerows(out)

print(len(out), "records;", len(gold_ids), "gold;", len(holdout_ids), "holdout")
print(collections.Counter(o["collection"] for o in out))
print(collections.Counter(o["decade"] for o in out))
