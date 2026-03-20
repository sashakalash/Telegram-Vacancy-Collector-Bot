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
