import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID, SHEET_NAME
from filter import CareerKeywords

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CAREER_PAGES_TAB = "career_pages"
CAREER_PAGES_HEADERS = ["url", "status", "jobs", "last_checked"]
LOCATIONS_TAB = "locations"
DEFAULT_LOCATION_WORDS = [
    "Argentina",
    "Latin America",
    "LATAM",
    "Latinoamérica",
    "Worldwide",
    "Global",
    "Anywhere",
]

_spreadsheet = None
_sheet = None  # cached sheet for writing vacancies


@dataclass
class CareerStatus:
    status: str
    jobs: int


@dataclass
class CareerRow:
    company: str
    keywords: list[str]
    text: str
    link: str


def _get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if credentials_json:
            creds = Credentials.from_service_account_info(
                json.loads(credentials_json), scopes=SCOPES
            )
        else:
            creds = Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
            )
        client = gspread.authorize(creds)
        _spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return _spreadsheet


def _get_sheet():
    """Lazy connection to the sheet for writing vacancies."""
    global _sheet
    if _sheet is None:
        spreadsheet = _get_spreadsheet()
        _sheet = spreadsheet.worksheet(SHEET_NAME)

        # Create header row if sheet is empty
        if _sheet.row_count == 0 or not _sheet.row_values(1):
            _sheet.append_row(
                ["Date", "Channel", "Keywords", "Text", "Link"],
                value_input_option="USER_ENTERED",
            )
            logger.info("Table header created")

    return _sheet


def load_channels() -> list[str]:
    """Loads list of channels from 'channels' sheet (handle column)."""
    try:
        ws = _get_spreadsheet().worksheet("channels")
        records = ws.get_all_records()
        channels = [row["handle"] for row in records if row.get("handle")]
        logger.info(f"Channels loaded from sheet: {len(channels)}")
        return channels
    except Exception as e:
        logger.error(f"Error loading channels: {e}", exc_info=True)
        return []


def load_keywords() -> tuple[list[str], list[str]]:
    """
    Loads keywords from 'keywords' sheet.
    Returns (include_keywords, exclude_keywords).
    """
    try:
        ws = _get_spreadsheet().worksheet("keywords")
        all_values = ws.get_all_values()
        logger.info(f"Keywords sheet raw values (first 10): {all_values[:10]}")
        if not all_values:
            return [], []
        headers = [h.strip().lower() for h in all_values[0]]
        logger.info(f"Keywords sheet headers: {headers}")
        try:
            kw_col = headers.index("keyword")
            type_col = headers.index("type")
        except ValueError:
            logger.error(f"Keywords sheet missing 'keyword' or 'type' column. Found: {headers}")
            return [], []
        include = [row[kw_col].strip() for row in all_values[1:] if len(row) > type_col and row[type_col].strip().lower() == "include" and row[kw_col].strip()]
        exclude = [row[kw_col].strip() for row in all_values[1:] if len(row) > type_col and row[type_col].strip().lower() == "exclude" and row[kw_col].strip()]
        logger.info(f"Keywords loaded: include={len(include)}, exclude={len(exclude)}")
        logger.debug(f"Exclude list: {exclude}")
        return include, exclude
    except Exception as e:
        logger.error(f"Error loading keywords: {e}")
        return [], []


def load_career_keywords() -> CareerKeywords:
    """Raises on Sheets errors, so a scan is retried instead of cutting every job."""
    rows = _get_spreadsheet().worksheet("keywords").get_all_values()
    headers = [h.strip().lower() for h in rows[0]] if rows else []
    kw_col, type_col = headers.index("keyword"), headers.index("type")
    words: dict[str, list[str]] = {}
    for row in rows[1:]:
        if len(row) > max(kw_col, type_col) and row[kw_col].strip():
            words.setdefault(row[type_col].strip().lower(), []).append(row[kw_col].strip())
    return CareerKeywords(
        titles=words.get("title", []),
        generic_titles=words.get("generic title", []),
        stack=words.get("stack", []),
        exclude=words.get("exclude", []),
    )


def write_row(channel: str, keywords: list[str], text: str, link: str) -> bool:
    """
    Writes a single row to the sheet.
    Returns True on success, False on error.
    """
    try:
        sheet = _get_sheet()
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            channel,
            ", ".join(keywords),
            text[:1000],  # truncate overly long messages
            link,
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Written to sheet: {channel} — {keywords}")
        return True
    except Exception as e:
        logger.error(f"Error writing to Google Sheets: {e}")
        return False


def _get_or_create_tab(title: str, first_rows: list[list[str]]) -> tuple[gspread.Worksheet, bool]:
    spreadsheet = _get_spreadsheet()
    try:
        return spreadsheet.worksheet(title), False
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(first_rows[0]))
        ws.update(values=first_rows, range_name="A1", value_input_option="RAW")
        logger.info(f"Created sheet page: {title}")
        return ws, True


def _first_column(rows: list[list[str]]) -> list[str]:
    return [row[0].strip() if row else "" for row in rows]


def load_career_pages() -> list[str]:
    """Career links from column A. Raises on Sheets errors so a scan is retried, not skipped."""
    ws, created = _get_or_create_tab(CAREER_PAGES_TAB, [CAREER_PAGES_HEADERS])
    if created:
        return []
    links = [v for v in _first_column(ws.get_all_values()) if v.lower().startswith("http")]
    return list(dict.fromkeys(links))


def load_location_words() -> list[str]:
    """Location words from column A, below the header. Raises on Sheets errors."""
    first_rows = [["word"]] + [[word] for word in DEFAULT_LOCATION_WORDS]
    ws, created = _get_or_create_tab(LOCATIONS_TAB, first_rows)
    if created:
        return list(DEFAULT_LOCATION_WORDS)
    return [v for v in _first_column(ws.get_all_values())[1:] if v]


def write_career_statuses(statuses: dict[str, CareerStatus], checked_at: str) -> None:
    """Re-reads the page first so links added or moved during a scan keep the right status."""
    ws, _ = _get_or_create_tab(CAREER_PAGES_TAB, [CAREER_PAGES_HEADERS])
    rows = ws.get_all_values()
    if not rows:
        return
    values = []
    for index, row in enumerate(rows):
        url = row[0].strip() if row else ""
        if url in statuses:
            values.append([statuses[url].status, statuses[url].jobs, checked_at])
        elif index == 0:
            values.append(CAREER_PAGES_HEADERS[1:])
        else:
            values.append((row[1:4] + ["", "", ""])[:3])
    ws.update(values=values, range_name=f"B1:D{len(values)}", value_input_option="RAW")


def append_career_rows(rows: list[CareerRow]) -> bool:
    """RAW so text from websites can never run as a spreadsheet formula."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [[now, r.company, ", ".join(r.keywords), r.text[:1000], r.link] for r in rows]
    try:
        _get_sheet().append_rows(values, value_input_option="RAW")
        logger.info(f"Written to sheet: {len(values)} career job(s)")
        return True
    except Exception as e:
        logger.error(f"Error writing career jobs to Google Sheets: {e}")
        return False
