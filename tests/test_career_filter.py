import unittest

from filter import career_keywords, location_matches

WORDS = ["Argentina", "Latin America", "LATAM", "Latinoamérica", "Worldwide", "Global", "Anywhere"]


class LocationMatchesTest(unittest.TestCase):
    def assert_kept(self, location):
        self.assertTrue(location_matches(location, WORDS), location)

    def assert_cut(self, location):
        self.assertFalse(location_matches(location, WORDS), location)

    def test_keeps_jobs_naming_a_listed_place(self):
        self.assert_kept("Buenos Aires, Argentina")
        self.assert_kept("Remote - LATAM")
        self.assert_kept("Home based - Worldwide")

    def test_ignores_case_and_accents(self):
        self.assert_kept("ARGENTINA")
        self.assert_kept("latinoamerica")

    def test_cuts_other_countries(self):
        self.assert_cut("New York City")
        self.assert_cut("Home based - EMEA")

    def test_keeps_plain_remote(self):
        self.assert_kept("Remote")
        self.assert_kept("Remoto")
        self.assert_kept("Fully Remote")
        self.assert_kept("Remote job")

    def test_cuts_remote_naming_another_place(self):
        self.assert_cut("Remote - Poland")
        self.assert_cut("Remote, US")

    def test_keeps_remote_naming_a_listed_place(self):
        self.assert_kept("Remote, Argentina")

    def test_any_location_of_several_is_enough(self):
        self.assert_kept("London | Argentina")
        self.assert_kept("Poland | Remote")
        self.assert_cut("London | Poland")

    def test_keeps_jobs_without_a_location(self):
        self.assert_kept(None)
        self.assert_kept("")

    def test_does_not_match_inside_a_longer_word(self):
        self.assert_cut("Globant Office, Madrid")


class CareerKeywordsTest(unittest.TestCase):
    def test_finds_keyword_in_description(self):
        found = career_keywords("Senior Software Engineer", "Must know React", ["React"], [])
        self.assertEqual(found, ["React"])

    def test_finds_keyword_in_title(self):
        found = career_keywords("React Developer", "", ["React"], [])
        self.assertEqual(found, ["React"])

    def test_excluded_word_in_title_rejects_job(self):
        found = career_keywords("PHP Developer", "React too", ["React"], ["PHP"])
        self.assertEqual(found, [])

    def test_excluded_word_only_in_description_keeps_job(self):
        found = career_keywords("Frontend Engineer", "React, some PHP", ["React"], ["PHP"])
        self.assertEqual(found, ["React"])

    def test_no_keyword_means_no_match(self):
        self.assertEqual(career_keywords("Accountant", "Excel", ["React"], []), [])


if __name__ == "__main__":
    unittest.main()
