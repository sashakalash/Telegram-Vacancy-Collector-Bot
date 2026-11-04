import re
import unicodedata

_PLAIN_REMOTE = re.compile(r"^\W*(?:fully\s+|100\W*)?(?:remote|remoto)(?:\s+job)?\W*$")


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


def location_matches(location: str | None, words: list[str]) -> bool:
    """True if any " | "-separated location names a listed place or is plain remote."""
    if not location or not location.strip():
        return True
    patterns = [re.compile(rf"(?<!\w){re.escape(_normalize(w))}(?!\w)") for w in words]
    for part in _normalize(location).split("|"):
        if _PLAIN_REMOTE.match(part) or any(p.search(part) for p in patterns):
            return True
    return False


def career_keywords(
    title: str, description: str, include: list[str], exclude: list[str]
) -> list[str]:
    """Include words check the whole job; exclude words check only the title."""
    title_lower = title.lower()
    if any(kw.lower() in title_lower for kw in exclude):
        return []
    return matched_keywords(f"{title}\n{description}", include)
