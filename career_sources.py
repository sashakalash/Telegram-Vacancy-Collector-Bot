import html as html_lib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET  # only for ParseError; parsing goes through defusedxml
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from defusedxml.ElementTree import fromstring as parse_xml

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20
RETRY_PAUSE_SECONDS = 5
RETRY_STATUSES = {429, 500, 502, 503, 504}
USER_AGENT = "Mozilla/5.0 (compatible; VacancyCollector/1.0)"
MAX_PAGE_TEXT = 50_000
MAX_LISTING_PAGES = 100
WORKDAY_PAGE_SIZE = 20
RIPPLING_PAGE_SIZE = 20

COUNTRY_CODES = {"AR": "Argentina"}
TRACKING_PARAMS = re.compile(r"^(utm_\w+|gh_src|gh_jid|source|ref|lever-\w+)$", re.I)

JOB_FOLDERS = {
    "job", "jobs", "position", "positions", "vacancy", "vacancies", "opening", "openings",
    "career", "careers", "role", "roles", "opportunities", "opportunity", "jobdetail", "detail",
    "job-listings", "join-our-team", "join-us", "empleo", "empleos", "oportunidad",
    "oportunidades", "o",
}
NEVER_IN_JOB_ADDRESS = {
    "become", "cookies", "hire", "how", "login", "our", "policy", "privacy", "terms", "what", "why",
}
VAGUE_WORDS = {
    "benefit", "benefits", "culture", "development", "diversity", "inclusion", "learning", "pool",
    "recommended", "saved", "talent",
}
NOT_A_JOB = {
    "about", "all", "apply", "benefits", "culture", "departments", "early-careers", "faq",
    "faqs", "internships", "life", "locations", "open-positions", "open-roles", "perks",
    "search", "students", "team", "teams", "values", "why-us",
}
NAVIGATION = {
    "assets", "blog", "blogs", "case-studies", "departments", "industries", "insights", "news",
    "products", "resources", "services", "solutions", "static", "wp-content",
}
FILE_TYPES = re.compile(r"\.(css|js|png|jpe?g|gif|svg|webp|ico|pdf|zip|xml|json|woff2?)$", re.I)
JOB_TITLE_WORD = re.compile(
    r"\b(engineer|developer|programmer|designer|analyst|architect|manager|specialist|consultant"
    r"|recruiter|administrator|scientist|tester|technician|desarrollador|desarrolladora"
    r"|ingeniero|ingeniera)\b",
    re.I,
)
TECH_ROLE_WORD = re.compile(r"devops|frontend|backend|fullstack|front-end|back-end|\b(qa|lead|sre)\b", re.I)
NAVIGATION_TEXT = re.compile(r"\b(hub|portal|community|program|docs|documentation|academy|partners)\b", re.I)
GENERIC_LINK_TEXT = re.compile(
    r"^\W*(apply\b.*|info\b.*apply|view\b.*|see\b.*|ver\b.*|aplica.*|postula.*"
    r"|learn more|read more|details|more|careers?|click here)?\W*$",
    re.I,
)
PAGE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
PLATFORM_JOB_LINK = re.compile(
    r"(linkedin\.com/jobs/view/"
    r"|apply\.workable\.com/(?:[\w-]+/)?j/"
    r"|\.bamboohr\.com/careers/\d+"
    r"|jobs\.lever\.co/[\w.-]+/[\w-]+"
    r"|jobs\.ashbyhq\.com/[\w.%-]+/[\w-]+"
    r"|greenhouse\.io/[\w-]+/jobs/\d+"
    r"|smartrecruiters\.com/(?:jobs/|[\w-]+/\d+)"
    r"|comeet\.com/jobs/"
    r"|\.breezy\.hr/p/)",
    re.I,
)


class SiteUnreadable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Job:
    title: str
    url: str
    location: str | None = None
    description: str | None = None
    # Returns (location or None to keep the current one, description).
    load_details: Callable[[], tuple[str | None, str | None]] | None = None
    # False when the title is a stand-in that load_details replaces with the page's own.
    title_is_final: bool = True

    @property
    def id(self) -> str:
        return _clean_url(self.url)


@dataclass
class SiteRead:
    jobs: list[Job]
    company: str
    is_feed: bool
    source: str


@dataclass
class _Feed:
    label: str
    company: str
    read: Callable[[], list[Job]]


def _fetch(url: str, data: bytes | None = None) -> tuple[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if data:
        headers["Content-Type"] = "application/json"
    for attempt in range(2):
        try:
            response = requests.request(
                "POST" if data else "GET", url, data=data, headers=headers, timeout=TIMEOUT_SECONDS
            )
        except requests.Timeout:
            raise SiteUnreadable("timed out") from None
        except requests.RequestException:
            raise SiteUnreadable("can't connect") from None
        if response.ok:
            return response.text, response.url
        if attempt or response.status_code not in RETRY_STATUSES:
            break
        time.sleep(RETRY_PAUSE_SECONDS)
    raise SiteUnreadable(_failure_reason(response.status_code))


def _failure_reason(status: int) -> str:
    if status in (401, 403, 429):
        return f"blocked ({status})"
    if status in (404, 410):
        return f"page not found ({status})"
    return f"site error ({status})"


def _json(url: str, data: bytes | None = None):
    return json.loads(_fetch(url, data)[0])


class _TextParser(HTMLParser):
    SKIPPED = {"script", "style", "noscript", "template", "head", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIPPED:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIPPED and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def _plain(markup: str | None) -> str:
    if not markup:
        return ""
    parser = _TextParser()
    parser.feed(markup)
    return " ".join(" ".join(parser.parts).split())[:MAX_PAGE_TEXT]


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(" ".join(self.text).split())))
            self.href = None

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)


def _clean_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _join(*parts) -> str | None:
    text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text or None


def _with_country(place: str | None, country: str | None) -> str | None:
    if not place:
        return country or None
    if not country or re.search(rf"(?<!\w){re.escape(country)}(?!\w)", place, re.I):
        return place
    return f"{place}, {country}"


def _either(places: list[str | None]) -> str | None:
    known = [p for p in places if p]
    return " | ".join(dict.fromkeys(known)) or None


def _read_greenhouse(slug: str) -> list[Job]:
    data = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    return [
        Job(
            title=j["title"],
            url=j["absolute_url"],
            location=(j.get("location") or {}).get("name"),
            description=_plain(html_lib.unescape(j.get("content") or "")),
        )
        for j in data["jobs"]
    ]


def _read_lever(slug: str) -> list[Job]:
    jobs = []
    for j in _json(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        categories = j.get("categories") or {}
        places = categories.get("allLocations") or [categories.get("location")]
        code = j.get("country")
        country = COUNTRY_CODES.get(code, code)
        lists = " ".join(f"{i.get('text', '')} {_plain(i.get('content'))}" for i in j.get("lists") or [])
        jobs.append(
            Job(
                title=j["text"],
                url=j["hostedUrl"],
                location=_either([_with_country(p, country) for p in places]),
                description=" ".join([j.get("descriptionPlain") or "", lists, j.get("additionalPlain") or ""]),
            )
        )
    return jobs


def _ashby_place(entry: dict) -> str | None:
    address = (entry.get("address") or {}).get("postalAddress") or {}
    return _with_country(entry.get("location"), address.get("addressCountry"))


def _read_ashby(slug: str) -> list[Job]:
    data = _json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    return [
        Job(
            title=j["title"],
            url=j["jobUrl"],
            location=_either([_ashby_place(j)] + [_ashby_place(s) for s in j.get("secondaryLocations") or []]),
            description=j.get("descriptionPlain") or "",
        )
        for j in data["jobs"]
        if j.get("isListed", True)
    ]


def _read_workable(slug: str) -> list[Job]:
    data = _json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    jobs = []
    for j in data["jobs"]:
        places = [_join(l.get("city"), l.get("region"), l.get("country")) for l in j.get("locations") or []]
        location = _either(places) or _join(j.get("city"), j.get("state"), j.get("country"))
        jobs.append(
            Job(
                title=j["title"],
                url=j["url"],
                location=location or ("Remote" if j.get("telecommuting") else None),
                description=_plain(j.get("description")),
            )
        )
    return jobs


def _read_gem(slug: str) -> list[Job]:
    return [
        Job(
            title=j["title"],
            url=j["absolute_url"],
            location=(j.get("location") or {}).get("name"),
            description=j.get("content_plain") or "",
        )
        for j in _json(f"https://api.gem.com/job_board/v0/{slug}/job_posts/")
    ]


def _read_bamboohr(subdomain: str) -> list[Job]:
    base = f"https://{subdomain}.bamboohr.com/careers"

    def details_for(job_id: str) -> Callable[[], tuple[str | None, str | None]]:
        def load() -> tuple[str | None, str | None]:
            opening = _json(f"{base}/{job_id}/detail")["result"]["jobOpening"]
            return None, _plain(opening.get("description"))

        return load

    jobs = []
    for j in _json(f"{base}/list")["result"]:
        ats = j.get("atsLocation") or {}
        place = (j.get("location") or {})
        location = _join(ats.get("city"), ats.get("state"), ats.get("province"), ats.get("country")) or _join(
            place.get("city"), place.get("state")
        )
        jobs.append(
            Job(
                title=j["jobOpeningName"],
                url=f"{base}/{j['id']}",
                location=location or ("Remote" if j.get("isRemote") else None),
                load_details=details_for(j["id"]),
            )
        )
    return jobs


def _read_zoho(host: str, page: str) -> list[Job]:
    data = _json(f"https://{host}/recruit/v2/public/Job_Openings?pagename={page}")
    jobs = []
    for j in data["data"]:
        location = _join(j.get("City"), j.get("State"), j.get("Country"))
        jobs.append(
            Job(
                title=j["Posting_Title"],
                url=j["$url"],
                location=location or ("Remote" if j.get("Remote_Job") == "Yes" else None),
                description=_plain(j.get("Job_Description")),
            )
        )
    return jobs


def _read_teamtailor(origin: str) -> list[Job]:
    root = parse_xml(_fetch(f"{origin}/jobs.rss")[0])
    jobs = []
    for item in root.iterfind(".//item"):
        places = [
            _join(place.findtext("{*}city"), place.findtext("{*}country"))
            for place in item.iterfind(".//{*}location")
        ]
        remote = (item.findtext("remoteStatus") or "none").strip().lower() != "none"
        jobs.append(
            Job(
                title=(item.findtext("title") or "").strip(),
                url=(item.findtext("link") or "").strip(),
                location=_either(places) or ("Remote" if remote else None),
                description=_plain(item.findtext("description")),
            )
        )
    return jobs


def _read_recruitee(origin: str) -> list[Job]:
    jobs = []
    for j in _json(f"{origin}/api/offers/")["offers"]:
        places = [_with_country(l.get("name"), l.get("country")) for l in j.get("locations") or []]
        jobs.append(
            Job(
                title=j["title"],
                url=j["careers_url"],
                location=_either(places) or j.get("location") or None,
                description=f"{_plain(j.get('description'))} {_plain(j.get('requirements'))}".strip(),
            )
        )
    return jobs


def _read_workday(host: str, tenant: str, site: str) -> list[Job]:
    base = f"https://{host}/wday/cxs/{tenant}/{site}"

    def details_for(path: str) -> Callable[[], tuple[str | None, str | None]]:
        def load() -> tuple[str | None, str | None]:
            info = _json(f"{base}{path}")["jobPostingInfo"]
            country = (info.get("country") or {}).get("descriptor")
            places = [(info.get("jobRequisitionLocation") or {}).get("descriptor")]
            places.append(_with_country(info.get("location"), country))
            places.extend(info.get("additionalLocations") or [])
            return _either(places), _plain(info.get("jobDescription"))

        return load

    jobs: list[Job] = []
    total = None
    for page in range(MAX_LISTING_PAGES):
        body = {"limit": WORKDAY_PAGE_SIZE, "offset": page * WORKDAY_PAGE_SIZE, "searchText": "", "appliedFacets": {}}
        data = _json(f"{base}/jobs", json.dumps(body).encode())
        # Workday can report total as 0 after the first page, so only trust the first.
        total = data.get("total", 0) if total is None else total
        postings = data.get("jobPostings") or []
        for j in postings:
            path, title = j.get("externalPath"), j.get("title")
            if path and title:
                jobs.append(Job(title=title, url=f"https://{host}/{site}{path}", load_details=details_for(path)))
        if not postings or (page + 1) * WORKDAY_PAGE_SIZE >= total:
            break
    return jobs


def _read_rippling(slug: str) -> list[Job]:
    base = f"https://ats.rippling.com/api/v2/board/{slug}/jobs"

    def details_for(job_id: str) -> Callable[[], tuple[str | None, str | None]]:
        def load() -> tuple[str | None, str | None]:
            description = _json(f"{base}/{job_id}").get("description") or {}
            return None, f"{_plain(description.get('company'))} {_plain(description.get('role'))}".strip()

        return load

    jobs = []
    for page in range(MAX_LISTING_PAGES):
        data = _json(f"{base}?page={page}&pageSize={RIPPLING_PAGE_SIZE}")
        for j in data.get("items") or []:
            places = [_with_country(l.get("name"), l.get("country")) for l in j.get("locations") or []]
            jobs.append(
                Job(title=j["name"], url=j["url"], location=_either(places), load_details=details_for(j["id"]))
            )
        if page + 1 >= (data.get("totalPages") or 0):
            break
    return jobs


# (label, pattern, slugs that are never a company, reader)
_SLUG_PLATFORMS = [
    (
        "Greenhouse",
        r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([\w-]+)",
        {"assets", "embed"},
        _read_greenhouse,
    ),
    ("Lever", r"(?:jobs\.lever\.co|api\.lever\.co/v0/postings)/([\w.-]+)", {"v0"}, _read_lever),
    ("Ashby", r"jobs\.ashbyhq\.com/([\w.%-]+)", {"ashby-embed-demo-org", "embed"}, _read_ashby),
    ("Workable", r"apply\.workable\.com/([\w-]+)", {"j", "api", "assets"}, _read_workable),
    ("Gem", r"jobs\.gem\.com/([\w-]+)", set(), _read_gem),
    ("Rippling", r"ats\.rippling\.com/(?:[a-z]{2}(?:-\w+)?/)?([\w-]+)/jobs", {"api"}, _read_rippling),
    ("BambooHR", r"([\w-]+)\.bamboohr\.com/careers", {"www", "resources"}, _read_bamboohr),
]
_WORKDAY = re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)")
_ZOHO = re.compile(r"(([\w-]+)\.zohorecruit\.\w+)/jobs/([\w%-]+)")


def _slug_feeds(text: str) -> list[_Feed]:
    feeds = []
    for label, pattern, ignored, reader in _SLUG_PLATFORMS:
        slug = next((s for s in re.findall(pattern, text) if s not in ignored), None)
        if slug:
            feeds.append(_Feed(label, unquote(slug), lambda r=reader, s=slug: r(s)))
    match = _WORKDAY.search(text)
    if match and match.group(3) != "wday":
        tenant, pod, site = match.groups()
        host = f"{tenant}.{pod}.myworkdayjobs.com"
        feeds.append(_Feed("Workday", tenant, lambda h=host, t=tenant, s=site: _read_workday(h, t, s)))
    return feeds


def _feeds_from_address(url: str) -> list[_Feed]:
    match = _ZOHO.search(url)
    if match:
        host, company, page = match.groups()
        return [_Feed("Zoho Recruit", company, lambda: _read_zoho(host, page))]
    return _slug_feeds(url)


def _feeds_from_page(url: str, page: str) -> list[_Feed]:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    company = _host(url)
    feeds = _slug_feeds(page)
    if "teamtailor-cdn.com/assets/careersite" in page:
        feeds.append(_Feed("Teamtailor", company, lambda: _read_teamtailor(origin)))
    if ".recruitee.com" in page:
        feeds.append(_Feed("Recruitee", company, lambda: _read_recruitee(origin)))
    return feeds


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _same_site(first: str, second: str) -> bool:
    return first.split(".")[-2:] == second.split(".")[-2:]


def _looks_like_job(url: str, text: str, page_url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or FILE_TYPES.search(parts.path):
        return False
    if PLATFORM_JOB_LINK.search(f"{parts.netloc}{parts.path}"):
        return True
    if not _same_site(_host(url), _host(page_url)):
        return False
    if parts.path.rstrip("/") == urlsplit(page_url).path.rstrip("/"):
        return False
    segments = [s.lower() for s in parts.path.split("/") if s]
    if not segments or NAVIGATION.intersection(segments):
        return False
    last = segments[-1]
    if last in NOT_A_JOB or last in JOB_FOLDERS:
        return False
    spaced = re.sub(r"[-_,]+", " ", last)
    if NEVER_IN_JOB_ADDRESS.intersection(spaced.split()):
        return False
    if JOB_FOLDERS.intersection(segments[:-1]):
        return _is_specific_job_address(last, spaced)
    if JOB_TITLE_WORD.search(spaced):
        return True
    return bool(JOB_TITLE_WORD.search(text[:100]) and not NAVIGATION_TEXT.search(text[:100]))


def _is_specific_job_address(last: str, spaced: str) -> bool:
    if JOB_TITLE_WORD.search(spaced) or TECH_ROLE_WORD.search(last):
        return True
    words = set(spaced.split())
    if VAGUE_WORDS.intersection(words):
        return False
    return any(c.isdigit() for c in last) or len(words) >= 3


def _title_from_address(url: str) -> str:
    segments = [unquote(s) for s in urlsplit(url).path.split("/") if s]
    named = [s for s in segments if not s.isdigit()]
    return re.sub(r"[-_]+", " ", named[-1] if named else url)


def _job_page_details(job: Job, needs_title: bool) -> Callable[[], tuple[str | None, str | None]]:
    def load() -> tuple[str | None, str | None]:
        try:
            page = _fetch(job.url)[0]
        except SiteUnreadable as e:
            logger.info(f"Could not open job page {job.url}: {e.reason}")
            return None, None
        match = PAGE_TITLE.search(page) if needs_title else None
        if match:
            job.title = " ".join(html_lib.unescape(match.group(1)).split())[:150] or job.title
        return None, _plain(page)

    return load


def _jobs_from_page(page: str, page_url: str) -> list[Job]:
    parser = _LinkParser()
    parser.feed(page)
    found: dict[str, tuple[Job, bool]] = {}
    for href, text in parser.links:
        url = _clean_url(urljoin(page_url, href.strip()))
        if not _looks_like_job(url, text, page_url):
            continue
        has_title = not GENERIC_LINK_TEXT.match(text)
        current = found.get(url)
        if current and (current[1] or not has_title):
            continue
        job = Job(title=text[:150] if has_title else _title_from_address(url), url=url, title_is_final=has_title)
        job.load_details = _job_page_details(job, needs_title=not has_title)
        found[url] = (job, has_title)
    return [job for job, _ in found.values()]


def _read_first_working_feed(feeds: list[_Feed], url: str) -> tuple[SiteRead | None, str | None]:
    """Returns (site, None), or (None, why the last feed failed), or (None, None) if no feeds."""
    reason = None
    for feed in feeds:
        try:
            return SiteRead(feed.read(), feed.company, True, feed.label), None
        except SiteUnreadable as e:
            reason = e.reason
        except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as e:
            reason = "unexpected feed data"
            logger.info(f"{feed.label} feed failed for {url}: {e!r}")
    return None, reason


def read_site(url: str, feed_only: bool = False) -> SiteRead:
    """Reads a link through its job feed, else its page links.

    feed_only: a feed that fails raises instead of using page links, because page
    links can have different addresses and every job would look new.
    """
    site, reason = _read_first_working_feed(_feeds_from_address(url), url)
    if site:
        return site
    if feed_only and reason:
        raise SiteUnreadable(reason)
    page, final_url = _fetch(url)
    site, reason = _read_first_working_feed(_feeds_from_page(final_url, page), url)
    if site:
        return site
    if feed_only and reason:
        raise SiteUnreadable(reason)
    return SiteRead(_jobs_from_page(page, final_url), _host(url), False, "page links")
