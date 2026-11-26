# AI-assisted metadata for historical photographs: a build-and-evaluate workflow

Code, prompts and results from a study of AI-assisted metadata creation for the **Prosch Albums** (photographs, ca. 1851-1906) at the University of Washington Libraries. It is the companion to the conference session *"From Traditional Metadata Practices to AI-Assisted Workflows: Building and Evaluating Metadata Enhancement Strategies"* (Amigos online conference).

**The argument:** AI metadata work only scales when it is treated as an engineered, evaluated workflow, not a prompt experiment. This repository shows one small, complete example: versioned prompts, constrained output, validation against authority files, a gold-standard benchmark, risk-based human review, and provenance on every AI value.

**What this repository does not contain:** the photographs, the catalog export, the AI output for each record, and the vocabulary lists built from catalog headings. Those stay with the library until it confirms what can be public (see `.gitignore`). You can read, adapt and run the code on your own collection; you cannot reproduce our exact numbers without our data.

## The workflow

```
photograph ──► prompt + vocabulary lists ──► model reply (JSON, checked against schema.json)
                                                   │
        ┌──────────────────────────────────────────┤
        ▼                                          ▼
 validate headings at id.loc.gov            score against cataloger-made gold records
 flag terms to review first                 (dev set for tuning, holdout for one final test)
        │
        ▼
 review sheet (Excel): accept / edit / reject every AI value ──► Dublin Core CSV
                                                                  (AI values stay labelled with model, prompt version, date)
```

Only the **image** and the prompt's **vocabulary lists** are sent to the model. The catalog's titles, notes and subjects for the item are never sent: they are the answer key.

## What the scripts do

| Script | What it does |
|---|---|
| `select_sample.py`, `download_images.py` | Choose a stratified sample and download its images from the library's public IIIF service (writes `manifest.csv`, `images/`). |
| `build_vocab.py` | Builds three vocabulary lists from the catalog's subject headings (LC subject/name headings, TGM genre terms, local headings), excluding the gold records, and checks each heading at id.loc.gov. |
| `describe.py` | Sends each image to a model, validates the reply against `schema.json`, and saves it with provenance (model, prompt version, date, tokens). Safe to re-run: it skips records already done. |
| `prompts/` | The versioned prompts: `v1` (free text), `v2`/`v2.1` (headings chosen from lists), `v3` (v2.1 plus five subject rules). |
| `validate_vocab.py`, `idloc.py`, `term_flags.py` | Check headings at id.loc.gov (main heading only; subdivision patterns need a cataloger) and flag terms for the reviewer. |
| `score.py` | Scores AI output against the gold records with partial credit; dev and holdout reported separately. |
| `sample_unmatched.py` | Samples AI terms that did not match gold, for a cataloger to judge (wrong / defensible / too generic). |
| `analyze_format_terms.py` | Offline analysis of an over-used "format" term (for example, how often "Photograph albums" appears and its effect on precision). |
| `calibrate.py`, `confidence_v2.py` | Test whether a confidence score predicts correctness; draft a term-level review flag. |
| `normalize_dates.py` | Rule-based conversion of the model's free-text date into display, search-years and EDTF fields (no AI call; has tests). |
| `make_review_sheet.py`, `export_dc.py`, `dc_mapping.csv` | Build the Excel review sheet; export accepted and edited values to Dublin Core with provenance columns. The mapping is an editable table. |
| `rubric_summary.py` | Summarizes hand ratings (1-3 scores, error categories, reviewer minutes). |
| `compare_models.py` | Compares two runs (for example two models) on the same gold records. |
| `match_authorities.py` | Looks up the places the AI found as exact headings at id.loc.gov (names and subjects) and as Wikidata items limited to Washington state. Suggestions only; rejected lookalikes are shown so wrong matches stay visible. No AI call. |
| `compare.py` | An HTML side-by-side viewer of the image, the AI output and the catalog record. |
| `demo.py`, `make_figures.py` | A one-command demo of one photo from image to Dublin Core, and the result charts. |
| `test_*.py` | Automated tests for date normalization, the review sheet and export, the rating summary, and the place-text handling used in authority matching. |

## Setup

Developed and tested on Python 3.15 on macOS.

```bash
python3 -m pip install -r requirements.txt
```

Calls to the model need an API key in the `ANTHROPIC_API_KEY` environment variable. The scripts read it from there and never write it anywhere. Set it for one terminal session only, for example:

```bash
read -s "ANTHROPIC_API_KEY?Paste key: "; export ANTHROPIC_API_KEY
```

Looking up headings at id.loc.gov (and places at Wikidata) needs internet access; the scripts pace their requests and stop with a clear error, rather than caching a failure, if a lookup fails. On some macOS Python installs you also need `SSL_CERT_FILE=/etc/ssl/cert.pem` in front of those commands (or run the "Install Certificates" command that came with your Python).

## Running it on your own collection

Bring your own CSV/tab-delimited export, images, and a gold set of existing cataloger records. Then, roughly:

```bash
python3 build_vocab.py                                   # vocabulary lists from your headings (excludes gold records)
python3 describe.py --n 30 --prompt v3 --only dev-gold   # costs API calls: state the number of calls before you run
python3 validate_vocab.py --prompt v3
python3 score.py --prompt v3
python3 match_authorities.py --prompt v3 --gold-only     # place suggestions from id.loc.gov and Wikidata (no API key needed)
python3 make_review_sheet.py --prompt v3                 # then review in Excel
python3 export_dc.py review_v3.xlsx
python3 -m unittest test_normalize_dates test_review_export test_rubric_summary
```

The scripts expect the column names of our CONTENTdm export (for example `Subjects (LCSH)`, `Date-EDTF`, `CONTENTdm number`); adjust them for your platform. Keep a **holdout** subset out of all prompt tuning and run it once at the end.

## What we found (Prosch Albums, 40 gold records: 30 dev, 10 holdout, model claude-sonnet-5-5)

| Prompt | Dev precision / recall | Holdout precision / recall |
|---|---|---|
| v1: free text | .085 / .171 | .077 / .155 |
| v2.1: vocabulary lists | .292 / .396 | .333 / .409 |
| v3: lists + five subject rules | .365 / .373 | .410 / .355 |

Partial-credit agreement with the catalogers' subject headings. The holdout has only 10 records (about 50 AI terms), so treat it as agreement in direction, not a precise number.

- **Controlled vocabulary lists were the biggest lever.** They also cost about 7 times more input tokens per photo (about 11k against 1.7k).
- **Error analysis beat the headline number.** Of 20 unmatched AI subjects a cataloger rated, 11 were too generic, 5 defensible and 4 wrong. One term, "Photograph albums" (an album-page term), was 8 of the 20 and was in 26 of 30 dev records until a prompt rule and a list change removed it.
- **A record-level confidence score did not predict correctness; a term-level flag did.** Terms the model rated "low" confidence, or whose heading is not authorized, matched the catalogers about half as often (for v3, 21% against 42%). The model's own "needs review" flag was true on every record.
- **A second model (claude-haiku-5-5) on the same prompt** matched on precision, found fewer subjects (lower recall), wrote about twice the output tokens, and two first-attempt replies were cut off at the output limit.
- **Date normalization** is rule-based and testable: 26 of 27 normalized dates were compatible with the gold date; narrative values are flagged for a cataloger.
- **Place matching to authorities** needed care. Taking the top search result returned lookalikes (Chelan, France; First Avenue in Manhattan; a planning council for "Seattle"). Looking places up as exact LC headings, with Washington-filtered Wikidata results, raised exact LC headings from 27 to 40 of 49 places and cut "no result" from 20 to 4 (5 more matched only the containing city). An exact heading proves the heading exists, not that it is the right place for the photograph, so these remain suggestions for a cataloger.

## Limitations

- **Small, single-collection study.** 40 gold records from one collection; no claim that it generalizes.
- **The gold is old and incomplete.** Created in 2000-2001; some headings are superseded, and a cataloger's review found many "misses" were defensible. "Matches gold" understates correctness.
- **Checking headings is partial.** id.loc.gov lookups check the main heading only; whether a subdivision is allowed under it needs a cataloger.
- **The model's self-reported flags were unusable** as a risk signal.
- **A prompt example:** the prompts since v2 include an illustrative example about a sign reading "Occidental", a name that appears in several catalog records. It only shows the format of a research lead and is unlikely to matter, but it is item-adjacent text in the prompt.
- **The vocabulary lists come from the same catalog** as the gold set (gold records excluded), so the model chooses from headings this catalog already uses.
- **The Dublin Core mapping is draft.** It follows a draft data dictionary, with open decisions (alt text, TGM, the hidden search-years field).
- **Authority matching is a suggestion list.** An exact LC heading means the heading exists; descriptive place text, hedged places and local names (for example a monument or a neighborhood nickname) often match only a broader place or nothing, and Wikidata still returns related items that are not the place itself.

## Responsible use

- **Never ask a model to identify real people from their faces.** Our prompts describe people by visible attributes and allow a name only when legible text in the image supplies it.
- **Check rights before sending images to any vendor.** `describe.py` skips any record marked `rights_cleared = N` in the manifest, but it cannot decide rights for you. In this study the images came from the library's public IIIF service and the `rights_cleared` column was left blank (rights statements were "Copyright Not Evaluated" or empty), so no record was marked N. Record a rights decision for your own images before sending them, and check the vendor's terms on data use and retention.
- **Keep AI values separate from approved data and label them.** Every AI value carries its model, prompt version and date; accepted and edited values are marked as such; nothing is written back to the catalog automatically.
- **Review before publishing.** AI-generated descriptions and subjects are suggestions for a cataloger, not final metadata. Watch for biased or outdated language.
- **Protect your key and your collection's data.** Never commit an API key; keep catalog exports and images out of public repositories until the collection's owners agree.

## License

Not yet chosen. Add a license file before publishing this repository.
