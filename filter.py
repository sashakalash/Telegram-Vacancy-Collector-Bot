import re
import unicodedata
from dataclasses import dataclass

_PLAIN_REMOTE = re.compile(r"^\W*(?:fully\s+|100\W*)?(?:remote|remoto)(?:\s+job)?\W*$")


@dataclass
class CareerKeywords:
    titles: list[str]
    generic_titles: list[str]
    stack: list[str]
    exclude: list[str]


def matches(text: str, include: list[str], exclude: list[str]) -> bool:
    """Returns True if text contains an include-word and does not contain an exclude-word."""
    if not text:
        return False
    text_lower = text.lower()
    if any(kw.lower() in text_lower for kw in exclude):
        return False
    return any(kw.lower() in text_lower for kw in include)


def matched_keywords(text: str, include: list[str]) -> list[str]:
    """Returns a list of matched include-keywords found in text."""
    if not text:
        return []
    text_lower = text.lower()
    return [kw for kw in include if kw.lower() in text_lower]


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _word_pattern(word: str) -> re.Pattern[str]:
    # Edges apply only beside letters and digits, so ".net" still finds "ASP.NET".
    word = _normalize(word)
    before = r"(?<!\w)" if re.match(r"\w", word) else ""
    after = r"(?!\w)" if re.search(r"\w$", word) else ""
    return re.compile(f"{before}{re.escape(word)}{after}")


def _found_in(text: str, words: list[str]) -> list[str]:
    normalized = _normalize(text)
    return [word for word in words if _word_pattern(word).search(normalized)]


def location_matches(location: str | None, words: list[str]) -> bool:
    """True if any " | "-separated location names a listed place or is plain remote."""
    if not location or not location.strip():
        return True
    patterns = [_word_pattern(w) for w in words]
    for part in _normalize(location).split("|"):
        if _PLAIN_REMOTE.match(part) or any(p.search(part) for p in patterns):
            return True
    return False


def title_may_match(title: str, keywords: CareerKeywords) -> bool:
    if _found_in(title, keywords.exclude):
        return False
    return bool(_found_in(title, keywords.titles + keywords.generic_titles))


def career_keywords(title: str, description: str, keywords: CareerKeywords) -> list[str]:
    """A role title is enough; a generic title also needs a stack word."""
    if not title_may_match(title, keywords):
        return []
    return _found_in(title, keywords.titles) or _found_in(f"{title}\n{description}", keywords.stack)
