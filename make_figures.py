"""Make the slide charts (PNG, large fonts) from the study's result files. NO API calls; reads files, writes figures/*.png.
Usage:  python3 make_figures.py
Reads:  summary.csv, calibration_terms.csv, calibration_records.csv (made by calibrate.py), outputs/<run>/unmatched_review_rated.csv,
        and the provenance (token counts) in outputs/<run>/*.json.
Everything on the charts is DEV data (the 30 dev gold records) unless a title says otherwise; the holdout is not used.
A chart for model A vs model B is not made yet because no second-model run exists.
Colors: one fixed color per prompt on every chart (v1 gray, v2.1 blue, v3 orange; Okabe-Ito colorblind-safe palette).
"""
import csv, glob, json, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

MODEL = "claude-sonnet-5-5"
COLOR = {"v1": "#8C8C8C", "v2.1": "#0072B2", "v3": "#E69F00"}
LABEL = {"v1": "v1 (free text)", "v2.1": "v2.1 (vocabulary lists)", "v3": "v3 (lists + 5 subject rules)"}
INK, GRID = "#222222", "#DDDDDD"
plt.rcParams.update({"font.size": 17, "axes.titlesize": 22, "axes.titleweight": "bold", "axes.labelsize": 17, "axes.edgecolor": INK,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 100, "savefig.dpi": 200, "text.color": INK,
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})
out = pathlib.Path("figures"); out.mkdir(exist_ok=True)
rd = lambda p: list(csv.DictReader(open(p, encoding="utf-8-sig")))
RUNS = ["v1", "v2.1", "v3"]

import textwrap
W, H = 13, 7.8
def header(fig, title, subtitle=None):
    """title (one line, bold) and subtitle (wrapped, gray) at the top left of the figure"""
    fig.text(0.02, 0.975, title, fontsize=25, fontweight="bold", va="top", ha="left")
    if subtitle: fig.text(0.02, 0.905, textwrap.fill(subtitle, 100), fontsize=15, color="#555555", va="top", ha="left", linespacing=1.3)
def finish(fig, ax, name, title, subtitle=None, ylabel=None):
    header(fig, title, subtitle)
    if ylabel: ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    fig.subplots_adjust(top=0.76, bottom=0.2, left=0.09, right=0.98)
    fig.savefig(out / name, facecolor="white"); plt.close(fig); print("wrote", out / name)
TICK = {"v1": "v1\n(free text)", "v2.1": "v2.1\n(vocabulary\nlists)", "v3": "v3\n(lists + 5\nsubject rules)"}

# ---- 1) precision and recall by prompt (dev, partial credit)
summ = {r["run"].split("_")[0]: r for r in rd("summary.csv") if r["subset"] == "dev"}
fig, ax = plt.subplots(figsize=(W, H)); w = 0.26
for k, run in enumerate(RUNS):
    for j, (metric, name) in enumerate((("pooled_precision_partial", "Precision"), ("pooled_recall_partial", "Recall"))):
        v = float(summ[run][metric]) * 100
        ax.bar(j + (k - 1) * w, v, w * 0.92, color=COLOR[run], label=LABEL[run] if j == 0 else None)
        ax.text(j + (k - 1) * w, v + 1, f"{v:.1f}%", ha="center", va="bottom", fontsize=16, fontweight="bold")
ax.set_xticks([0, 1]); ax.set_xticklabels(["Precision\n(share of AI subjects that match\nthe catalogers)", "Recall\n(share of cataloger subjects\nthe AI found)"])
ax.set_ylim(0, 60); ax.set_yticks(range(0, 61, 10)); ax.set_yticklabels([f"{t}%" for t in range(0, 61, 10)])
ax.legend(frameon=False, loc="upper left", fontsize=15)
finish(fig, ax, "fig1_precision_recall.png", "Vocabulary lists lifted precision from 8.5% to 29.2%",
       "30 dev gold records; partial-credit match against 2000-2001 cataloger subjects (a rough yardstick). v3 adds five subject rules to v2.1.")

# ---- 2) term flags
terms = rd("calibration_terms.csv")
def flagged(t): return t["model_confidence"] == "low" or t["vocab_status"] in ("none", "variant")
fig, ax = plt.subplots(figsize=(W, H)); w = 0.36
for k, run in enumerate(RUNS):
    for j, (is_flag, label, shade) in enumerate(((False, "Not flagged", COLOR[run]), (True, "Flagged for review", "#FFFFFF"))):
        ts = [float(t["credit"]) for t in terms if t["run"] == run and flagged(t) == is_flag]
        v = sum(ts) / len(ts) * 100
        ax.bar(k + (j - 0.5) * w, v, w * 0.92, color=shade, edgecolor=COLOR[run], linewidth=2.5, hatch="//" if is_flag else None)
        ax.text(k + (j - 0.5) * w, v + 1, f"{v:.0f}%", ha="center", va="bottom", fontsize=17, fontweight="bold")
        ax.text(k + (j - 0.5) * w, v + 5.5, f"{len(ts)} terms", ha="center", va="bottom", fontsize=13, color="#555555")
ax.set_xticks(range(3)); ax.set_xticklabels([TICK[r] for r in RUNS])
ax.set_ylim(0, 60); ax.set_yticks(range(0, 61, 10)); ax.set_yticklabels([f"{t}%" for t in range(0, 61, 10)])
from matplotlib.patches import Patch
ax.legend(handles=[Patch(facecolor="#BBBBBB", edgecolor="#555555", label="Not flagged"), Patch(facecolor="white", edgecolor="#555555", hatch="//", label="Flagged for review")],
          frameon=False, loc="upper left", fontsize=15)
finish(fig, ax, "fig2_term_flags.png", "Flagged terms match the catalogers about half as often",
       "Flag = the model said 'low' confidence, or the heading is not authorized. Mean gold credit per subject term, 30 dev records.", "Mean gold credit per term")

# ---- 3) verdicts on 20 unmatched terms
rated = rd(f"outputs/v2.1_{MODEL}/unmatched_review_rated.csv")
n_album = sum(r["verdict"] == "too_generic" and r["ai_term"] == "Photograph albums" for r in rated)
counts = {v: sum(r["verdict"] == v for r in rated) for v in ("too_generic", "defensible", "wrong")}
fig, ax = plt.subplots(figsize=(W, 6.6))
ax.barh([2], [n_album], color="#D55E00", height=0.55); ax.barh([2], [counts["too_generic"] - n_album], left=[n_album], color="#E69F00", height=0.55)
ax.barh([1], [counts["defensible"]], color="#009E73", height=0.55); ax.barh([0], [counts["wrong"]], color="#CC79A7", height=0.55)
ax.text(n_album / 2, 2, f"'Photograph albums'\n{n_album}", ha="center", va="center", color="white", fontsize=15, fontweight="bold")
ax.text(n_album + (counts["too_generic"] - n_album) / 2, 2, f"{counts['too_generic'] - n_album} broad\nheadings", ha="center", va="center", fontsize=13, fontweight="bold")
ax.text(counts["too_generic"] + 0.2, 2, f"{counts['too_generic']} of 20 too generic", va="center", fontsize=16, fontweight="bold")
ax.text(counts["defensible"] + 0.2, 1, f"{counts['defensible']} of 20 defensible", va="center", fontsize=16, fontweight="bold")
ax.text(counts["wrong"] + 0.2, 0, f"{counts['wrong']} of 20 wrong", va="center", fontsize=16, fontweight="bold")
ax.set_yticks([]); ax.set_xlim(0, 16); ax.set_xticks([]); ax.spines["left"].set_visible(False); ax.spines["bottom"].set_visible(False)
header(fig, "Most unmatched AI subjects were generic, not wrong", "A cataloger rated 20 unmatched v2.1 subject terms (dev records only; a small sample).")
fig.subplots_adjust(top=0.78, bottom=0.04, left=0.03, right=0.98)
fig.savefig(out / "fig3_verdicts.png", facecolor="white"); plt.close(fig); print("wrote", out / "fig3_verdicts.png")

# ---- 4) tokens per record (cost)
tok = {}
for run in RUNS:
    recs = [json.load(open(f))["provenance"] for f in glob.glob(f"outputs/{run}_{MODEL}/[0-9]*.json")]
    tok[run] = (sum(r["input_tokens"] for r in recs) / len(recs), sum(r["output_tokens"] for r in recs) / len(recs), len(recs))
fig, ax = plt.subplots(figsize=(W, H)); w = 0.36
for k, run in enumerate(RUNS):
    for j, (v, shade) in enumerate(((tok[run][0], COLOR[run]), (tok[run][1], "#FFFFFF"))):
        ax.bar(k + (j - 0.5) * w, v / 1000, w * 0.92, color=shade, edgecolor=COLOR[run], linewidth=2.5, hatch="//" if j else None)
        ax.text(k + (j - 0.5) * w, v / 1000 + 0.2, f"{v / 1000:.1f}k", ha="center", va="bottom", fontsize=16, fontweight="bold")
ax.set_xticks(range(3)); ax.set_xticklabels([TICK[r] for r in RUNS]); ax.set_ylim(0, 14)
ax.legend(handles=[Patch(facecolor="#BBBBBB", edgecolor="#555555", label="Input tokens per photo"), Patch(facecolor="white", edgecolor="#555555", hatch="//", label="Output tokens per photo")],
          frameon=False, loc="upper left", fontsize=15)
finish(fig, ax, "fig4_tokens.png", "The vocabulary lists cost roughly 7x more input per photo",
       f"Average tokens per record ({tok['v1'][2]} records for v1 and v2.1, {tok['v3'][2]} for v3). The lists travel with every request.", "Thousands of tokens")

# ---- 5) does the record-level tier predict precision?
recs = rd("calibration_records.csv")
fig, ax = plt.subplots(figsize=(W, H)); w = 0.36; tiers = ["sample-check", "sample review"]
for k, run in enumerate(["v2.1", "v3"]):
    for j, tier in enumerate(tiers):
        ps = [float(r["precision"]) for r in recs if r["run"] == run and r["tier"] == tier and r["precision"] != "nan"]
        v = sum(ps) / len(ps) * 100
        ax.bar(j + (k - 0.5) * w, v, w * 0.92, color=COLOR[run], label=LABEL[run] if j == 0 else None)
        ax.text(j + (k - 0.5) * w, v + 1, f"{v:.0f}%", ha="center", va="bottom", fontsize=16, fontweight="bold")
        ax.text(j + (k - 0.5) * w, 1.5, f"{len(ps)} records", ha="center", va="bottom", fontsize=13, color="white")
ax.set_xticks([0, 1]); ax.set_xticklabels(["Tier: sample-check\n(highest confidence score)", "Tier: sample review\n(lower confidence score)"])
ax.set_ylim(0, 60); ax.set_yticks(range(0, 61, 10)); ax.set_yticklabels([f"{t}%" for t in range(0, 61, 10)])
ax.legend(frameon=False, loc="upper left", fontsize=15)
finish(fig, ax, "fig5_tier_vs_precision.png", "Record-level confidence did not predict correctness",
       "Mean gold precision by confidence tier, 30 dev records. Higher-tier records were not more precise, which is why we flag terms, not records.", "Mean gold precision")
