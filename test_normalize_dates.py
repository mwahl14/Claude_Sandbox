"""Tests for normalize_dates.py.   Run:  python3 -m unittest test_normalize_dates -v
Each case is: input text -> (display, dates, edtf, status). `dates` is written as a range 'A-B' meaning every year from A to B
(or a space-separated list for several separate dates). Expected values come from the rules in normalize_dates.py's docstring."""
import unittest
from normalize_dates import normalize, agreement, gold_years

def yrs(a, b): return " ".join(str(y) for y in range(a, b + 1))

CASES = [
    # exact years, full dates, months
    ("1889",                       ("1889", "1889", "1889", "ok")),
    ("1905-11-13",                 ("November 13, 1905", "1905", "1905-11-13", "ok")),
    ("June 21, 1905",              ("June 21, 1905", "1905", "1905-06-21", "ok")),
    ("September 1911",             ("September, 1911", "1911", "1911-09", "ok")),
    ("October 1881",               ("October, 1881", "1881", "1881-10", "ok")),
    # approximate years and "circa" forms
    ("circa 1896",                 ("approximately 1896", yrs(1891, 1901), "1896~", "ok")),
    ("ca. 1892",                   ("approximately 1892", yrs(1887, 1897), "1892~", "ok")),
    ("about 1890",                 ("approximately 1890", yrs(1885, 1895), "1890~", "ok")),
    ("mid-1880s",                  ("approximately 1885", yrs(1880, 1890), "1885~", "ok")),
    ("early 1880s",                ("approximately 1882", yrs(1877, 1887), "1882~", "ok")),
    # uncertain years
    ("probably 1889",              ("1889?", yrs(1884, 1894), "1889?", "ok")),
    ("1889 (possibly)",            ("1889?", yrs(1884, 1894), "1889?", "ok")),
    # exact ranges and decades
    ("1880-1889",                  ("between 1880 and 1889", yrs(1880, 1889), "1880/1889", "ok")),
    ("1869–1870",             ("between 1869 and 1870", yrs(1869, 1870), "1869/1870", "ok")),
    ("1880s",                      ("between 1880 and 1889", yrs(1880, 1889), "1880/1889", "ok")),
    ("1900s",                      ("between 1900 and 1909", yrs(1900, 1909), "1900/1909", "ok")),
    ("1890s-1900s",                ("between 1890 and 1909", yrs(1890, 1909), "1890/1909", "ok")),
    ("1860s-1880s",                ("between 1860 and 1889", yrs(1860, 1889), "1860/1889", "ok")),
    ("1865-1870s",                 ("between 1865 and 1879", yrs(1865, 1879), "1865/1879", "ok")),
    ("1870s-1893",                 ("between 1870 and 1893", yrs(1870, 1893), "1870/1893", "ok")),
    ("1850-1910",                  ("between 1850 and 1910", yrs(1850, 1910), "1850/1910", "ok")),
    # approximate or uncertain ranges: "?" on both ends and five extra years each side
    ("ca. 1890-1910",              ("between 1890 and 1910?", yrs(1885, 1915), "1890?/1910?", "ok")),
    ("circa 1890s-1910s",          ("between 1890 and 1919?", yrs(1885, 1924), "1890?/1919?", "ok")),
    ("1880s-1890s (possibly)",     ("between 1880 and 1899?", yrs(1875, 1904), "1880?/1899?", "ok")),
    ("1860s-1880s (tentative)",    ("between 1860 and 1889?", yrs(1855, 1894), "1860?/1889?", "ok")),
    ("early 20th century (approx. 1900s-1920s)", ("between 1900 and 1933?", yrs(1895, 1938), "1900?/1933?", "ok")),
    ("late 19th century",          ("between 1867 and 1899?", yrs(1862, 1904), "1867?/1899?", "ok")),
    # our own display format must read back the same (used when a reviewer edits a date)
    ("approximately 1885",         ("approximately 1885", yrs(1880, 1890), "1885~", "ok")),
    ("1889?",                      ("1889?", yrs(1884, 1894), "1889?", "ok")),
    ("between 1880 and 1889",      ("between 1880 and 1889", yrs(1880, 1889), "1880/1889", "ok")),
    ("between 1890 and 1910?",     ("between 1890 and 1910?", yrs(1885, 1915), "1890?/1910?", "ok")),
    ("September, 1911",            ("September, 1911", "1911", "1911-09", "ok")),
    # commentary is ignored
    ("1875-1876 (photographs); captions likely added later", ("between 1875 and 1876", yrs(1875, 1876), "1875/1876", "ok")),
    ("1851 (date of the cabin per caption); date of the drawing unknown, likely later", ("1851", "1851", "1851", "ok")),
    ("1890s-1900s (photographs); house built 1853 per caption", ("between 1890 and 1909", yrs(1890, 1909), "1890/1909", "ok")),
    ("mid-1880s (view); print or album page possibly later", ("approximately 1885", yrs(1880, 1890), "1885~", "ok")),
    ("1861–1895 (photograph probably made within this period)", ("between 1861 and 1895", yrs(1861, 1895), "1861/1895", "ok")),
    # several dates in one value
    ("1882 and 1886",              ("1882; 1886", "1882 1886", "1882 1886", "multiple")),
    ("1880 (upper photograph); May 1888 (lower photograph)", ("1880; May, 1888", "1880 1888", "1880 1888-05", "multiple")),
    ("ca. 1863 and ca. 1866",      ("approximately 1863; approximately 1866", yrs(1858, 1871), "1863~ 1866~", "multiple")),
    # unknown, narrative, empty
    ("unknown; likely early 20th century or late 19th century", ("", "", "", "unknown")),
    ("unknown; probably between 1850 and 1910", ("between 1850 and 1910?", yrs(1845, 1915), "1850?/1910?", "review")),
    ("Upper image depicts 1856; lower photograph dated 1870.", ("", "", "", "review")),
    ("Photographs: before 1889. Buildings constructed 1858 and 1859 per captions.", ("", "", "", "review")),
    ("Late 19th to early 20th century (possibly 1889)", ("", "", "", "review")),
    ("", ("", "", "", "unknown")),
    (None, ("", "", "", "unknown")),
]

class NormalizeTests(unittest.TestCase):
    def test_cases(self):
        for text, expected in CASES:
            with self.subTest(text=text):
                r = normalize(text)
                self.assertEqual((r["display"], r["dates"], r["edtf"], r["status"]), expected)

    def test_gold_years(self):
        self.assertEqual(gold_years("1856 1870?/1874?"), {1856, 1870, 1871, 1872, 1873, 1874})
        self.assertEqual(gold_years("1911-09"), {1911})
        self.assertEqual(gold_years(""), set())

    def test_agreement(self):
        self.assertEqual(agreement(normalize("1889"), "1889"), "exact")
        self.assertEqual(agreement(normalize("1880s"), "1880/1889"), "exact")
        self.assertEqual(agreement(normalize("1885"), "1880/1889"), "inside gold span")
        self.assertEqual(agreement(normalize("1880-1889"), "1885/1895"), "overlap")
        self.assertEqual(agreement(normalize("1860"), "1889"), "no overlap")
        self.assertEqual(agreement(normalize("unknown"), "1889"), "no AI date")

if __name__ == "__main__":
    unittest.main()
