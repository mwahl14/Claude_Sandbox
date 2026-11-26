"""Tests for rubric_summary.py.   Run:  python3 -m unittest test_rubric_summary -v     (uses made-up ratings in a temp folder; touches no real sheets)"""
import csv, os, pathlib, subprocess, sys, tempfile, unittest
from rubric_summary import summarize

FIELDS = ["id", "subset", "ai_title", "gold_title", "ai_description", "ai_alt_text", "description_score_1to3", "alt_text_score_1to3",
          "reviewer_minutes", "error_category", "error_notes"]
def row(i, subset, d="", a="", m="", e=""):
    return dict(id=i, subset=subset, ai_title="t", gold_title="g", ai_description="x", ai_alt_text="y", description_score_1to3=d,
                alt_text_score_1to3=a, reviewer_minutes=m, error_category=e, error_notes="")

class SummaryTests(unittest.TestCase):
    def test_means_distribution_minutes_errors(self):
        rows = [row("1", "dev", 3, 2, 4, "hallucination"), row("2", "dev", 2, 2, 6, ""), row("3", "dev", 1, 3, 5, "Hallucination "),
                row("4", "dev", "", "", "", ""), row("5", "holdout", 3, 3, 2, "over-generic subject")]
        s, warn = summarize(rows, "vX"); dev, hold = s
        self.assertEqual(warn, [])
        self.assertEqual((dev["subset"], dev["records"]), ("dev", 4)); self.assertEqual(hold["subset"], "holdout")
        self.assertEqual((dev["desc_rated"], dev["desc_mean"], dev["desc_dist"]), (3, 2.0, "1:1 2:1 3:1"))
        self.assertEqual((dev["alt_rated"], dev["alt_mean"]), (3, 2.33))
        self.assertEqual((dev["minutes_n"], dev["minutes_total"], dev["minutes_mean"]), (3, 15.0, 5.0))
        self.assertEqual(dev["errors"], {"hallucination": 2})                         # case and spaces ignored
        self.assertEqual((hold["records"], hold["desc_mean"]), (1, 3.0))              # holdout kept separate

    def test_bad_values_warn_and_are_ignored(self):
        s, warn = summarize([row("1", "dev", 5, "two", "abc", ""), row("2", "dev", 2, 2, 3, "")], "vX")
        self.assertEqual(len(warn), 3)
        self.assertEqual((s[0]["desc_rated"], s[0]["desc_mean"], s[0]["alt_rated"], s[0]["minutes_total"]), (1, 2.0, 1, 3.0))

    def test_nothing_rated_yet(self):
        s, warn = summarize([row("1", "dev"), row("2", "dev")], "vX")
        self.assertEqual((s[0]["desc_rated"], s[0]["desc_mean"], s[0]["minutes_mean"], s[0]["errors"]), (0, "", "", {}))

class PrepareTests(unittest.TestCase):
    def test_prepare_copies_dev_only_and_never_overwrites(self):
        tmp = pathlib.Path(tempfile.mkdtemp()); run = tmp / "outputs" / "vT_claude-sonnet-5-5"; run.mkdir(parents=True)
        with open(run / "rubric.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows([row("1", "dev"), row("2", "dev"), row("3", "holdout")])
        script = str(pathlib.Path("rubric_summary.py").resolve())
        out = subprocess.run([sys.executable, script, "--prepare", "--prompts", "vT"], cwd=tmp, capture_output=True, text=True).stdout
        self.assertIn("2 records to rate", out)
        dst = run / "rubric_rated.csv"; dst.write_text(dst.read_text(encoding="utf-8-sig").replace("dev,t", "dev,MY RATING", 1), encoding="utf-8-sig")
        out2 = subprocess.run([sys.executable, script, "--prepare", "--prompts", "vT"], cwd=tmp, capture_output=True, text=True).stdout
        self.assertIn("not overwritten", out2); self.assertIn("MY RATING", dst.read_text(encoding="utf-8-sig"))

if __name__ == "__main__":
    unittest.main()
