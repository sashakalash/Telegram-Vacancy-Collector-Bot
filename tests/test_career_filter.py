import unittest

from filter import CareerKeywords, career_keywords, location_matches, title_may_match

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


KEYWORDS = CareerKeywords(
    titles=["frontend", "front-end", "full stack"],
    generic_titles=["software engineer", "developer"],
    stack=["TypeScript", "React"],
    exclude=["PHP", ".net", "c++", "UK"],
)


class CareerKeywordsTest(unittest.TestCase):
    def test_role_in_title_is_enough(self):
        self.assertEqual(career_keywords("Senior Frontend Engineer", "", KEYWORDS), ["frontend"])
        self.assertEqual(career_keywords("FRONT-END Lead", "Excel", KEYWORDS), ["front-end"])

    def test_generic_title_needs_a_stack_word_in_the_description(self):
        self.assertEqual(career_keywords("Software Engineer", "Must know TypeScript", KEYWORDS), ["TypeScript"])
        self.assertEqual(career_keywords("Software Engineer", "Excel", KEYWORDS), [])

    def test_stack_word_in_a_generic_title_counts(self):
        self.assertEqual(career_keywords("Developer (React)", "", KEYWORDS), ["React"])

    def test_stack_word_alone_cannot_rescue_another_title(self):
        title = "Adobe Multi-Solution Architect"
        self.assertEqual(career_keywords(title, "stacks such as TypeScript", KEYWORDS), [])
        self.assertEqual(career_keywords("POS Customer Support", "React", KEYWORDS), [])

    def test_words_match_whole_words_only(self):
        self.assertEqual(career_keywords("Frontends Guru", "", KEYWORDS), [])
        self.assertEqual(career_keywords("Software Engineering Manager", "React", KEYWORDS), [])
        self.assertEqual(career_keywords("Software Engineer", "Reactive systems", KEYWORDS), [])
        java = CareerKeywords([], ["developer"], ["java"], [])
        self.assertEqual(career_keywords("Developer", "JavaScript", java), [])

    def test_excluded_word_in_title_rejects_even_a_role_title(self):
        self.assertEqual(career_keywords("PHP Frontend Developer", "React", KEYWORDS), [])

    def test_excluded_word_only_in_description_keeps_job(self):
        self.assertEqual(career_keywords("Frontend Engineer", "some PHP", KEYWORDS), ["frontend"])

    def test_excluded_word_must_be_a_whole_word(self):
        self.assertEqual(career_keywords("Frontend Engineer, Duke Energy", "", KEYWORDS), ["frontend"])
        self.assertEqual(career_keywords("Frontend Engineer, UK", "", KEYWORDS), [])

    def test_words_with_symbols_still_match(self):
        self.assertEqual(career_keywords("ASP.NET Developer", "React", KEYWORDS), [])
        self.assertEqual(career_keywords("C++ Developer", "React", KEYWORDS), [])

    def test_non_breaking_space_in_a_title_still_matches(self):
        self.assertEqual(career_keywords("Full\xa0Stack Engineer", "", KEYWORDS), ["full stack"])


class TitleMayMatchTest(unittest.TestCase):
    def test_role_and_generic_titles_may_match(self):
        self.assertTrue(title_may_match("Frontend Engineer", KEYWORDS))
        self.assertTrue(title_may_match("Software Engineer", KEYWORDS))

    def test_other_and_excluded_titles_cannot(self):
        self.assertFalse(title_may_match("Accountant", KEYWORDS))
        self.assertFalse(title_may_match("PHP Developer", KEYWORDS))


if __name__ == "__main__":
    unittest.main()
