import json
import logging
import os
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_CREDENTIALS_FILE, SPREADSHEET_ID, SHEET_NAME

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_spreadsheet = None
_sheet = None  # cached sheet for writing vacancies


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
        records = ws.get_all_records()
        include = [row["keyword"].strip() for row in records if row.get("type") == "include" and row.get("keyword", "").strip()]
        exclude = [row["keyword"].strip() for row in records if row.get("type") == "exclude" and row.get("keyword", "").strip()]
        logger.info(f"Keywords loaded: include={len(include)}, exclude={len(exclude)}")
        return include, exclude
    except Exception as e:
        logger.error(f"Error loading keywords: {e}")
        return [], []


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
