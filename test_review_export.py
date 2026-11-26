"""End-to-end test of the review tool on 5 dev records: make the sheet -> simulate a reviewer -> export Dublin Core.
Run from the project folder:   python3 -m unittest test_review_export -v
Uses only the existing v3 outputs and writes into a temporary folder, so nothing in the project changes. No API calls."""
import csv, hashlib, pathlib, subprocess, sys, tempfile, unittest
from openpyxl import load_workbook

IDS = "213,220,25,54,249"

def run(*cmd):
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr + p.stdout
    return p.stdout

class ReviewRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog_hash = hashlib.sha256(pathlib.Path("Prosch_Export.txt").read_bytes()).hexdigest()
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        sheet = cls.tmp / "review_test.xlsx"
        cls.make_out = run("make_review_sheet.py", "--prompt", "v3", "--ids", IDS, "--out", str(sheet))
        wb = load_workbook(sheet); ws = wb["Review"]
        col = {c.value: i + 1 for i, c in enumerate(ws[1])}
        cls.edited_subject = None; cls.rows = {}
        first_213 = True
        for r in range(2, ws.max_row + 1):
            rid, field, key = str(ws.cell(r, col["record_id"]).value), ws.cell(r, col["field"]).value, ws.cell(r, col["row_key"]).value
            set_ = lambda name, v: ws.cell(r, col[name], v)
            cls.rows[key] = r
            if rid == "249":
                if field == "title": set_("decision", "accept")      # only the title is reviewed: record stays 'partial'
                continue
            set_("decision", "accept")
            if rid == "213" and first_213: set_("reviewer_minutes", 7.5); set_("error_category", "over-generic subject"); first_213 = False
            if key == "213|subject_lcsh|1": set_("decision", "edit"); set_("edited_value", "Test Heading--Washington (State)")
            if key == "220|subject_tgm|1": set_("decision", "reject")
            if key == "220|alt_text|1": set_("decision", "edit")                       # edit with no value -> warning, skipped
            if key == "25|date|1": set_("decision", "edit"); set_("edited_value", "approximately 1885")
            if key == "54|date|1": set_("decision", "edit"); set_("edited_value", "between 1856 and 1870?")
        wb.save(sheet)
        cls.export_out = run("export_dc.py", str(sheet), "--out", str(cls.tmp / "dc_test.csv"))
        with open(cls.tmp / "dc_test.csv", encoding="utf-8-sig") as f: cls.dc = {r["record_id"]: r for r in csv.DictReader(f)}
        cls.sheet_rows = ws.max_row - 1

    def test_sheet_has_rows_for_5_records(self):
        self.assertIn("5 records", self.make_out)
        self.assertGreater(self.sheet_rows, 30)

    def test_accepted_title_and_provenance(self):
        r = self.dc["213"]
        self.assertTrue(r["dc:title"]); self.assertEqual(r["dc:title_provenance"], "ai-accepted")
        self.assertEqual(r["ai_prompt_version"], "v3"); self.assertEqual(r["ai_model"], "claude-sonnet-5-5")

    def test_edited_value_replaces_ai_value(self):
        r = self.dc["213"]
        self.assertIn("Test Heading--Washington (State)", r["dc:subject"])
        values, provs = r["dc:subject"].split(" ; "), r["dc:subject_provenance"].split(" ; ")
        self.assertEqual(provs[values.index("Test Heading--Washington (State)")], "ai-edited")   # the edited value carries its own provenance
        self.assertIn("ai-accepted", r["dc:subject_provenance"])

    def test_rejected_row_is_dropped(self):
        n_tgm_in_sheet = sum(1 for k in self.rows if k.startswith("220|subject_tgm|"))
        n_tgm_out = len([v for v in self.dc["220"]["dc:subject.tgm"].split(" ; ") if v])
        self.assertEqual(n_tgm_out, n_tgm_in_sheet - 1)

    def test_dates_accepted(self):
        r = self.dc["220"]                                   # AI said "September 1911"
        self.assertEqual((r["dc:date"], r["dc:created"], r["dc:date.search"]), ("September, 1911", "1911-09", "1911"))

    def test_edited_date_is_renormalized(self):
        r = self.dc["25"]
        self.assertEqual((r["dc:date"], r["dc:created"]), ("approximately 1885", "1885~"))
        self.assertEqual(r["dc:created_provenance"], "ai-edited")
        r = self.dc["54"]                                    # AI date could not be normalized; reviewer typed one
        self.assertEqual((r["dc:date"], r["dc:created"]), ("between 1856 and 1870?", "1856?/1870?"))

    def test_pending_rows_are_not_exported_and_marked_partial(self):
        r = self.dc["249"]
        self.assertEqual(r["review_status"], "partial"); self.assertTrue(r["dc:title"]); self.assertEqual(r["dc:subject"], "")
        self.assertEqual(self.dc["213"]["review_status"], "reviewed")

    def test_edit_without_value_warns_and_is_skipped(self):
        self.assertIn("marked edit but there is no value", self.export_out)
        self.assertEqual(self.dc["220"]["local:alt-text"], "")

    def test_minutes_and_error_log(self):
        self.assertEqual(float(self.dc["213"]["reviewer_minutes"]), 7.5)
        with open(self.tmp / "dc_test_errors.csv", encoding="utf-8-sig") as f: errs = list(csv.DictReader(f))
        self.assertEqual(len(errs), 1); self.assertEqual(errs[0]["error_category"], "over-generic subject")

    def test_flag_columns(self):
        ws = load_workbook(self.tmp / "review_test.xlsx")["Review"]
        header = [c.value for c in ws[1]]; col = {h: i for i, h in enumerate(header)}
        self.assertIn("review_flag", header); self.assertIn("flag_reason", header)
        flagged = 0; last = {}                                  # (record, field) -> has an unflagged row been seen yet?
        for row in ws.iter_rows(min_row=2, values_only=True):
            flag, why, field, rid = row[col["review_flag"]], row[col["flag_reason"]], row[col["field"]], row[col["record_id"]]
            if flag == "Y":
                flagged += 1
                self.assertTrue(field.startswith("subject"), "only subject terms are flagged")
                self.assertTrue(why, "a flagged row must say why")
                self.assertFalse(last.get((rid, field), False), "flagged rows must come before unflagged ones in each record and field")
            else:
                self.assertFalse(why, "no reason without a flag")
                if field.startswith("subject"): last[(rid, field)] = True
        self.assertGreater(flagged, 0)
        self.assertIn(f"subject terms flagged for review: {flagged} of", self.make_out)

    def test_flag_columns_do_not_change_export(self):
        self.assertNotIn("review_flag", self.dc["213"])         # the flag is for the reviewer, not part of the Dublin Core export

    def test_catalog_untouched(self):
        self.assertEqual(hashlib.sha256(pathlib.Path("Prosch_Export.txt").read_bytes()).hexdigest(), self.catalog_hash)

if __name__ == "__main__":
    unittest.main()
