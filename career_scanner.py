import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from career_sources import Job, SiteRead, SiteUnreadable, read_site
from config import CAREER_SCAN_INTERVAL_HOURS
from filter import CareerKeywords, career_keywords, location_matches, title_may_match
from notifier import send_career_alert, send_career_notification
from sheets import (
    CareerRow,
    CareerStatus,
    append_career_rows,
    load_career_keywords,
    load_career_pages,
    load_location_words,
    write_career_statuses,
)
from state import (
    get_career_site,
    get_last_career_scan,
    record_career_site,
    set_last_career_scan,
)

logger = logging.getLogger(__name__)

RETRY_SECONDS = 3600
NOTIFICATION_PAUSE_SECONDS = 1.1
DETAILS_PAUSE_SECONDS = 0.3
MAX_DETAILS_PER_SITE = 200


@dataclass
class Match:
    job: Job
    keywords: list[str]
    company: str


@dataclass
class SiteOutcome:
    status: CareerStatus
    matches: list[Match] = field(default_factory=list)
    problem: str | None = None


def _unreadable(url: str, record: dict, reason: str) -> SiteOutcome:
    record_career_site(url, last_jobs=0)
    return SiteOutcome(
        CareerStatus(f"Can't read: {reason}", 0),
        problem=reason if record["last_jobs"] > 0 else None,
    )


def _status_for(site: SiteRead) -> CareerStatus:
    if not site.jobs:
        return CareerStatus("No jobs found", 0)
    label = f"{site.source} feed" if site.is_feed else site.source
    return CareerStatus(f"OK - {label}", len(site.jobs))


def _filter_new_jobs(
    site: SiteRead, seen: set[str], keywords: CareerKeywords, words: list[str]
) -> tuple[list[Match], list[str]]:
    matches: list[Match] = []
    settled: list[str] = []
    details_used = 0
    for job in site.jobs:
        if job.id in seen:
            continue
        if job.location and not location_matches(job.location, words):
            settled.append(job.id)
            continue
        if job.title_is_final and not title_may_match(job.title, keywords):
            settled.append(job.id)
            continue
        if job.load_details:
            if details_used >= MAX_DETAILS_PER_SITE:
                continue
            details_used += 1
            try:
                location, job.description = job.load_details()
            except (SiteUnreadable, ValueError, KeyError, TypeError, AttributeError) as e:
                logger.info(f"Will retry job later, details failed for {job.url}: {e!r}")
                continue
            job.location = location if location is not None else job.location
            time.sleep(DETAILS_PAUSE_SECONDS)
            if not location_matches(job.location, words):
                settled.append(job.id)
                continue
        found = career_keywords(job.title, job.description or "", keywords)
        if found:
            matches.append(Match(job, found, site.company))
        else:
            settled.append(job.id)
    return matches, settled


def _examine_site(url: str, keywords: CareerKeywords, words: list[str]) -> SiteOutcome:
    record = get_career_site(url)
    try:
        site = read_site(url, feed_only=record["is_feed"])
    except SiteUnreadable as e:
        return _unreadable(url, record, e.reason)

    count = len(site.jobs)
    status = _status_for(site)
    problem = "shows no jobs" if count == 0 and record["last_jobs"] > 0 else None
    # Feeds and page links can list one job under different addresses, so a switch stays quiet too.
    if not record["seeded"] or site.is_feed != record["is_feed"]:
        # A plain page showing nothing may simply be unreadable, so it stays unseeded.
        record_career_site(
            url,
            seen=[job.id for job in site.jobs],
            seeded=site.is_feed or count > 0,
            last_jobs=count,
            is_feed=site.is_feed,
        )
        return SiteOutcome(status, problem=problem)

    matches, settled = _filter_new_jobs(site, record["seen"], keywords, words)
    record_career_site(url, seen=settled, last_jobs=count)
    return SiteOutcome(status, matches, problem)


def _examine_site_safely(url: str, keywords: CareerKeywords, words: list[str]) -> SiteOutcome:
    try:
        return _examine_site(url, keywords, words)
    except Exception as e:
        logger.error(f"Career page {url} failed: {e}", exc_info=True)
        return _unreadable(url, get_career_site(url), "unexpected error")


def _row_for(match: Match) -> CareerRow:
    job = match.job
    text = f"{job.title}\n{job.location or 'not listed'}\n\n{job.description or ''}"
    return CareerRow(match.company, match.keywords, text, job.url)


async def _deliver(url: str, matches: list[Match]) -> None:
    written = await asyncio.to_thread(append_career_rows, [_row_for(m) for m in matches])
    if not written:
        logger.error(f"Sheet write failed for {url}; its {len(matches)} job(s) retry next scan")
        return
    record_career_site(url, seen=[m.job.id for m in matches])
    for match in matches:
        await send_career_notification(
            company=match.company,
            title=match.job.title,
            location=match.job.location,
            keywords=match.keywords,
            link=match.job.url,
        )
        await asyncio.sleep(NOTIFICATION_PAUSE_SECONDS)


async def run_career_scan() -> bool:
    """Returns False if the scan was skipped, so the caller retries soon instead of tomorrow."""
    keywords = await asyncio.to_thread(load_career_keywords)
    if not keywords.titles:
        logger.warning("Career scan skipped: no words with type 'title' in the keywords sheet")
        return False
    pages = await asyncio.to_thread(load_career_pages)
    words = await asyncio.to_thread(load_location_words)
    if not pages or not words:
        logger.info(f"Career scan skipped: {len(pages)} links, {len(words)} location words")
        return False

    logger.info(f"Career scan started: {len(pages)} links")
    statuses: dict[str, CareerStatus] = {}
    found = 0
    for url in pages:
        outcome = await asyncio.to_thread(_examine_site_safely, url, keywords, words)
        statuses[url] = outcome.status
        if outcome.matches:
            found += len(outcome.matches)
            await _deliver(url, outcome.matches)
        if outcome.problem:
            await send_career_alert(url, outcome.problem)

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    await asyncio.to_thread(write_career_statuses, statuses, checked_at)
    logger.info(f"Career scan finished: {len(pages)} links, {found} new matches")
    return True


def seconds_until_due(last_scan: str | None, now: datetime, interval_hours: float) -> float:
    if not last_scan:
        return 0
    try:
        elapsed = (now - datetime.fromisoformat(last_scan)).total_seconds()
    except (ValueError, TypeError):
        return 0
    return max(0, interval_hours * 3600 - elapsed)


async def career_scan_loop() -> None:
    while True:
        now = datetime.now(timezone.utc)
        await asyncio.sleep(seconds_until_due(get_last_career_scan(), now, CAREER_SCAN_INTERVAL_HOURS))
        try:
            finished = await run_career_scan()
        except Exception as e:
            logger.error(f"Career scan failed: {e}", exc_info=True)
            finished = False
        if finished:
            set_last_career_scan(datetime.now(timezone.utc).isoformat())
        else:
            await asyncio.sleep(RETRY_SECONDS)
