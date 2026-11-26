"""Tests for the place-text handling in match_authorities.py (no network).   Run:  python3 -m unittest test_match_authorities -v
Inputs are place strings the model really produced for the dev records."""
import unittest
from match_authorities import entities, city_context, label_variants

class EntityTests(unittest.TestCase):
    def test_simple_names_and_state_words_dropped(self):
        self.assertEqual(entities("Chelan, Washington"), ["Chelan"])
        self.assertEqual(entities("Seattle, Washington"), ["Seattle"])
        self.assertEqual(entities("Port Madison, Kitsap County, Washington"), ["Port Madison", "Kitsap County"])
        self.assertEqual(entities("Alki Point, Seattle, Washington"), ["Alki Point", "Seattle"])

    def test_parentheticals_removed(self):
        self.assertEqual(entities("Puget Sound (Washington State)"), ["Puget Sound"])
        self.assertEqual(entities("Seattle, Washington (early settlement, Elliott Bay)"), ["Seattle"])
        self.assertEqual(entities("Lakeside (state not given in the caption)"), ["Lakeside"])
        self.assertEqual(entities("Saint Mark's Church (city and state not stated in the caption)"), ["Saint Mark's Church"])

    def test_streets_pulled_out_of_descriptive_text(self):
        self.assertEqual(entities("Southeast corner of Fourth Avenue and James Street, Seattle, Washington"), ["Fourth Avenue", "James Street", "Seattle"])
        self.assertEqual(entities("Waterfront from Marion Street to Union Street, Seattle, Washington"), ["Marion Street", "Union Street", "Seattle"])
        self.assertEqual(entities("First Avenue, from Yesler Way north, Seattle, Washington"), ["First Avenue", "Yesler Way", "Seattle"])
        self.assertEqual(entities("Ninth Avenue, near Lake Union (city not named in the caption; probably Seattle)"), ["Ninth Avenue"])

    def test_descriptive_phrases_are_not_names(self):
        self.assertEqual(entities("Wharves at Washington, Main and Jackson Streets, Seattle, Washington"), ["Jackson Street", "Seattle"])
        self.assertEqual(entities("Seattle waterfront near the Yesler wharf, looking toward Columbia Street"), ["Columbia Street"])
        self.assertEqual(entities("Freeport, later Milton and West Seattle, Washington Territory"), ["Freeport"])   # 'later ...' is descriptive wording

    def test_descriptive_only_text_gives_nothing(self):
        self.assertEqual(entities("South end of Seattle, Washington"), [])
        self.assertEqual(entities(""), [])

    def test_city_context_includes_hedges_and_other_places(self):
        self.assertEqual(city_context(["Fremont, on Lake Union", "First Avenue, Seattle, Washington"]), "Seattle")
        self.assertEqual(city_context(["Ninth Avenue (probably Seattle)"]), "Seattle")
        self.assertEqual(city_context(["Chelan, Washington"]), "")

    def test_label_variants_follow_lc_form(self):
        self.assertEqual(label_variants("Yesler Way", "Seattle"), ["Yesler Way (Seattle, Wash.)", "Yesler Way (Wash.)"])
        self.assertEqual(label_variants("Seattle", "Seattle"), ["Seattle (Wash.)"])
        self.assertEqual(label_variants("Chelan", ""), ["Chelan (Wash.)"])
        self.assertEqual(label_variants("First Avenue South", "Seattle")[:2], ["First Avenue South (Seattle, Wash.)", "First Avenue South (Wash.)"])

if __name__ == "__main__":
    unittest.main()
