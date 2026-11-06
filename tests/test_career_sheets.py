import unittest
from unittest.mock import MagicMock, patch

import gspread

import sheets


def worksheet_not_found():
    response = MagicMock()
    response.json.return_value = {"error": {"code": 404, "message": "x", "status": "x"}}
    return gspread.exceptions.WorksheetNotFound("missing")


class FakeWorksheet:
    def __init__(self, values=None):
        self.values = values or []
        self.updates = []

    def get_all_values(self):
        return self.values

    def update(self, values=None, range_name=None, value_input_option=None):
        self.updates.append((values, range_name, value_input_option))


class FakeSpreadsheet:
    def __init__(self, tabs=None):
        self.tabs = tabs or {}

    def worksheet(self, name):
        if name not in self.tabs:
            raise worksheet_not_found()
        return self.tabs[name]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWorksheet()
        return self.tabs[title]


def with_spreadsheet(spreadsheet):
    return patch.object(sheets, "_get_spreadsheet", return_value=spreadsheet)


class LoadCareerPagesTest(unittest.TestCase):
    def test_reads_links_from_first_column(self):
        tab = FakeWorksheet(
            [
                ["url", "status", "jobs", "last_checked"],
                [" https://a.com/careers ", "OK", "3", "x"],
                ["", "", "", ""],
                ["not a link"],
                ["https://b.com/jobs"],
                ["https://a.com/careers"],
            ]
        )
        with with_spreadsheet(FakeSpreadsheet({"career_pages": tab})):
            self.assertEqual(sheets.load_career_pages(), ["https://a.com/careers", "https://b.com/jobs"])

    def test_creates_the_page_with_headers_when_missing(self):
        spreadsheet = FakeSpreadsheet()
        with with_spreadsheet(spreadsheet):
            self.assertEqual(sheets.load_career_pages(), [])
        values, range_name, _ = spreadsheet.tabs["career_pages"].updates[0]
        self.assertEqual(values, [["url", "status", "jobs", "last_checked"]])
        self.assertEqual(range_name, "A1")

    def test_a_sheets_failure_is_raised_not_hidden_as_empty(self):
        broken = MagicMock()
        broken.worksheet.side_effect = gspread.exceptions.GSpreadException("down")
        with with_spreadsheet(broken), self.assertRaises(gspread.exceptions.GSpreadException):
            sheets.load_career_pages()


class LoadCareerKeywordsTest(unittest.TestCase):
    def keywords_from(self, rows):
        tab = FakeWorksheet(rows)
        with with_spreadsheet(FakeSpreadsheet({"keywords": tab})):
            return sheets.load_career_keywords()

    def test_sorts_words_by_type(self):
        keywords = self.keywords_from(
            [
                ["keyword", "type"],
                ["frontend", "title"],
                [" full stack ", " Title "],
                ["software engineer", "generic title"],
                ["typescript", "stack"],
                ["php", "exclude"],
                ["web", "include"],
                ["", "title"],
                ["no type", ""],
            ]
        )
        self.assertEqual(keywords.titles, ["frontend", "full stack"])
        self.assertEqual(keywords.generic_titles, ["software engineer"])
        self.assertEqual(keywords.stack, ["typescript"])
        self.assertEqual(keywords.exclude, ["php"])

    def test_finds_columns_by_name(self):
        keywords = self.keywords_from([["Type", "Keyword"], ["title", "frontend"]])
        self.assertEqual(keywords.titles, ["frontend"])

    def test_a_missing_column_is_raised_not_hidden_as_empty(self):
        with self.assertRaises(ValueError):
            self.keywords_from([["word"], ["frontend"]])

    def test_a_sheets_failure_is_raised_not_hidden_as_empty(self):
        broken = MagicMock()
        broken.worksheet.side_effect = gspread.exceptions.GSpreadException("down")
        with with_spreadsheet(broken), self.assertRaises(gspread.exceptions.GSpreadException):
            sheets.load_career_keywords()


class LoadLocationWordsTest(unittest.TestCase):
    def test_reads_words_from_first_column(self):
        tab = FakeWorksheet([["word"], ["Argentina"], [" LATAM "], [""]])
        with with_spreadsheet(FakeSpreadsheet({"locations": tab})):
            self.assertEqual(sheets.load_location_words(), ["Argentina", "LATAM"])

    def test_creates_the_page_with_your_words_when_missing(self):
        spreadsheet = FakeSpreadsheet()
        with with_spreadsheet(spreadsheet):
            words = sheets.load_location_words()
        self.assertEqual(
            words,
            ["Argentina", "Latin America", "LATAM", "Latinoamérica", "Worldwide", "Global", "Anywhere"],
        )
        values, range_name, _ = spreadsheet.tabs["locations"].updates[0]
        self.assertEqual(values[0], ["word"])
        self.assertEqual(values[1:], [[w] for w in words])
        self.assertEqual(range_name, "A1")


class WriteCareerStatusesTest(unittest.TestCase):
    def test_writes_status_beside_each_link_and_leaves_others_alone(self):
        tab = FakeWorksheet(
            [
                ["url", "status", "jobs", "last_checked"],
                ["https://a.com", "old", "1", "before"],
                ["https://added-during-scan.com"],
                ["https://b.com", "old", "2", "before"],
            ]
        )
        statuses = {
            "https://a.com": sheets.CareerStatus("OK - Ashby feed", 3),
            "https://b.com": sheets.CareerStatus("Can't read: blocked (403)", 0),
        }
        with with_spreadsheet(FakeSpreadsheet({"career_pages": tab})):
            sheets.write_career_statuses(statuses, "2026-11-04 10:00")
        values, range_name, option = tab.updates[0]
        self.assertEqual(range_name, "B1:D4")
        self.assertEqual(option, "RAW")
        self.assertEqual(
            values,
            [
                ["status", "jobs", "last_checked"],
                ["OK - Ashby feed", 3, "2026-11-04 10:00"],
                ["", "", ""],
                ["Can't read: blocked (403)", 0, "2026-11-04 10:00"],
            ],
        )


class AppendCareerRowsTest(unittest.TestCase):
    def test_writes_text_literally_so_formulas_cannot_run(self):
        sheet = MagicMock()
        rows = [sheets.CareerRow("acme", ["React"], "=IMPORTXML(1)" + "x" * 2000, "https://a.com/1")]
        with patch.object(sheets, "_get_sheet", return_value=sheet):
            self.assertTrue(sheets.append_career_rows(rows))
        written, kwargs = sheet.append_rows.call_args
        row = written[0][0]
        self.assertEqual(row[1:3], ["acme", "React"])
        self.assertEqual(len(row[3]), 1000)
        self.assertEqual(row[4], "https://a.com/1")
        self.assertEqual(kwargs["value_input_option"], "RAW")

    def test_reports_failure(self):
        sheet = MagicMock()
        sheet.append_rows.side_effect = gspread.exceptions.GSpreadException("down")
        with patch.object(sheets, "_get_sheet", return_value=sheet):
            self.assertFalse(sheets.append_career_rows([sheets.CareerRow("a", [], "t", "l")]))


if __name__ == "__main__":
    unittest.main()
