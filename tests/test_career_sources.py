import json
import unittest
from unittest.mock import patch

import career_sources
from career_sources import SiteUnreadable, read_site


class FakeWeb:
    """Answers career_sources._fetch from a url -> body map; unknown urls are a 404."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def __call__(self, url, data=None):
        self.requested.append(url)
        if url not in self.pages:
            raise SiteUnreadable("page not found (404)")
        body = self.pages[url]
        if isinstance(body, Exception):
            raise body
        text = body if isinstance(body, str) else json.dumps(body)
        return text, url


def read_with(pages, url):
    web = FakeWeb(pages)
    with patch.object(career_sources, "_fetch", web):
        return read_site(url), web


GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/caylent/jobs?content=true"
GREENHOUSE_BODY = {
    "jobs": [
        {
            "title": "Frontend Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/caylent/jobs/1",
            "location": {"name": "Argentina"},
            "content": "&lt;p&gt;React &amp;amp; TypeScript&lt;/p&gt;",
        }
    ]
}


class GreenhouseTest(unittest.TestCase):
    def test_reads_jobs_from_feed_ignoring_saved_filters(self):
        site, _ = read_with(
            {GREENHOUSE_API: GREENHOUSE_BODY},
            "https://job-boards.greenhouse.io/caylent?keyword=frontend",
        )
        self.assertTrue(site.is_feed)
        self.assertEqual(site.company, "caylent")
        job = site.jobs[0]
        self.assertEqual(job.title, "Frontend Engineer")
        self.assertEqual(job.url, "https://job-boards.greenhouse.io/caylent/jobs/1")
        self.assertEqual(job.location, "Argentina")
        self.assertEqual(job.description, "React & TypeScript")
        self.assertIsNone(job.load_details)


class PlatformFeedsTest(unittest.TestCase):
    def test_lever_turns_country_code_into_argentina(self):
        body = [
            {
                "text": "Support Engineer",
                "hostedUrl": "https://jobs.lever.co/Allata/1",
                "categories": {"location": "Buenos Aires"},
                "country": "AR",
                "descriptionPlain": "About us",
                "lists": [{"text": "Skills", "content": "<li>React</li>"}],
                "additionalPlain": "Benefits",
            }
        ]
        site, _ = read_with(
            {"https://api.lever.co/v0/postings/Allata?mode=json": body},
            "https://jobs.lever.co/Allata?location=Buenos%20Aires",
        )
        job = site.jobs[0]
        self.assertEqual(job.location, "Buenos Aires, Argentina")
        for piece in ("About us", "Skills", "React", "Benefits"):
            self.assertIn(piece, job.description)

    def test_lever_keeps_every_listed_location(self):
        body = [
            {
                "text": "Engineer",
                "hostedUrl": "https://jobs.lever.co/acme/1",
                "categories": {"location": "Remote", "allLocations": ["Remote", "Lima"]},
                "country": "US",
            }
        ]
        site, _ = read_with(
            {"https://api.lever.co/v0/postings/acme?mode=json": body},
            "https://jobs.lever.co/acme",
        )
        self.assertEqual(site.jobs[0].location, "Remote, US | Lima, US")

    def test_ashby_adds_country_and_skips_unlisted_jobs(self):
        body = {
            "jobs": [
                {
                    "title": "Engineer",
                    "jobUrl": "https://jobs.ashbyhq.com/lazer/1",
                    "isListed": True,
                    "location": "Remote",
                    "address": {"postalAddress": {"addressCountry": "Canada"}},
                    "secondaryLocations": [
                        {"location": "USA", "address": {"postalAddress": {"addressCountry": "US"}}}
                    ],
                    "descriptionPlain": "React",
                },
                {
                    "title": "Hidden",
                    "jobUrl": "https://jobs.ashbyhq.com/lazer/2",
                    "isListed": False,
                    "location": "Remote",
                },
            ]
        }
        site, _ = read_with(
            {"https://api.ashbyhq.com/posting-api/job-board/lazer": body},
            "https://jobs.ashbyhq.com/lazer",
        )
        self.assertEqual(len(site.jobs), 1)
        self.assertEqual(site.jobs[0].location, "Remote, Canada | USA, US")

    def test_workable_reads_locations_list(self):
        body = {
            "jobs": [
                {
                    "title": "AI Engineer",
                    "url": "https://apply.workable.com/j/ABC",
                    "telecommuting": True,
                    "country": "Argentina",
                    "city": "",
                    "state": "",
                    "locations": [{"country": "Argentina", "city": "", "region": None}],
                    "description": "<p>React</p>",
                }
            ]
        }
        site, _ = read_with(
            {"https://apply.workable.com/api/v1/widget/accounts/azumo?details=true": body},
            "https://apply.workable.com/azumo/",
        )
        self.assertEqual(site.jobs[0].location, "Argentina")
        self.assertEqual(site.jobs[0].description, "React")

    def test_workable_with_no_place_but_remote_flag_is_plain_remote(self):
        body = {
            "jobs": [
                {
                    "title": "Engineer",
                    "url": "https://apply.workable.com/j/X",
                    "telecommuting": True,
                    "locations": [],
                    "description": "",
                }
            ]
        }
        site, _ = read_with(
            {"https://apply.workable.com/api/v1/widget/accounts/azumo?details=true": body},
            "https://apply.workable.com/azumo/",
        )
        self.assertEqual(site.jobs[0].location, "Remote")

    def test_gem_reads_plain_text(self):
        body = [
            {
                "title": "Platform Engineer",
                "absolute_url": "https://jobs.gem.com/felix/1",
                "location": {"name": "United States"},
                "content_plain": "React",
            }
        ]
        site, _ = read_with(
            {"https://api.gem.com/job_board/v0/felix/job_posts/": body},
            "https://jobs.gem.com/felix",
        )
        self.assertEqual(site.jobs[0].location, "United States")
        self.assertEqual(site.jobs[0].description, "React")

    def test_zoho_treats_empty_place_with_remote_flag_as_remote(self):
        body = {
            "data": [
                {
                    "Posting_Title": "Assistant",
                    "$url": "https://thehireboost.zohorecruit.com/jobs/Careers/1",
                    "City": "",
                    "State": "",
                    "Country": "",
                    "Remote_Job": "Yes",
                    "Job_Description": "<p>React</p>",
                }
            ]
        }
        url = "https://thehireboost.zohorecruit.com/recruit/v2/public/Job_Openings?pagename=Careers"
        site, _ = read_with({url: body}, "https://thehireboost.zohorecruit.com/jobs/Careers")
        self.assertEqual(site.jobs[0].location, "Remote")
        self.assertEqual(site.jobs[0].description, "React")


class JobsWithSeparateDetailsTest(unittest.TestCase):
    def test_bamboohr_opens_job_for_description(self):
        pages = {
            "https://smith.bamboohr.com/careers/list": {
                "result": [
                    {
                        "id": "226",
                        "jobOpeningName": "Engineer",
                        "atsLocation": {"country": "Argentina", "state": None, "province": None, "city": "Cordoba"},
                        "location": {"city": None, "state": None},
                        "isRemote": None,
                    }
                ]
            },
            "https://smith.bamboohr.com/careers/226/detail": {
                "result": {"jobOpening": {"description": "<p>React</p>"}}
            },
            "https://smithcommerce.com/about/careers/": '<a href="https://smith.bamboohr.com/careers/226">x</a>',
        }
        site, web = read_with(pages, "https://smithcommerce.com/about/careers/")
        self.assertTrue(site.is_feed)
        job = site.jobs[0]
        self.assertEqual(job.url, "https://smith.bamboohr.com/careers/226")
        self.assertEqual(job.location, "Cordoba, Argentina")
        self.assertIsNone(job.description)
        self.assertNotIn("https://smith.bamboohr.com/careers/226/detail", web.requested)
        with patch.object(career_sources, "_fetch", web):
            self.assertEqual(job.load_details(), (None, "React"))

    def test_workday_pages_through_jobs_and_reads_location_from_details(self):
        base = "https://intive.wd3.myworkdayjobs.com/wday/cxs/intive/Intive"
        calls = []

        def web(url, data=None):
            calls.append((url, data))
            if url == f"{base}/jobs":
                offset = json.loads(data)["offset"]
                if offset == 0:
                    postings = [{"title": f"Job {i}", "externalPath": f"/job/x/{i}"} for i in range(20)]
                else:
                    postings = [{"title": "Last", "externalPath": "/job/x/last"}]
                return json.dumps({"total": 21, "jobPostings": postings}), url
            info = {
                "location": "Buenos Aires",
                "additionalLocations": ["Lima"],
                "country": {"descriptor": "Argentina"},
                "jobRequisitionLocation": {"descriptor": "Remote: Argentina"},
                "jobDescription": "<p>React</p>",
            }
            return json.dumps({"jobPostingInfo": info}), url

        with patch.object(career_sources, "_fetch", web):
            site = read_site("https://intive.wd3.myworkdayjobs.com/Intive")
            self.assertEqual(len(site.jobs), 21)
            job = site.jobs[-1]
            self.assertEqual(job.url, "https://intive.wd3.myworkdayjobs.com/Intive/job/x/last")
            self.assertIsNone(job.location)
            location, description = job.load_details()
        self.assertEqual(location, "Remote: Argentina | Buenos Aires, Argentina | Lima")
        self.assertEqual(description, "React")

    def test_rippling_reads_description_from_job(self):
        pages = {
            "https://ats.rippling.com/api/v2/board/aspenview/jobs?page=0&pageSize=20": {
                "items": [
                    {
                        "id": "abc",
                        "name": "Engineer",
                        "url": "https://ats.rippling.com/aspenview/jobs/abc",
                        "locations": [{"name": "Remote", "country": "Argentina"}],
                    }
                ],
                "totalPages": 1,
            },
            "https://ats.rippling.com/api/v2/board/aspenview/jobs/abc": {
                "description": {"company": "<p>About</p>", "role": "<p>React</p>"}
            },
        }
        site, web = read_with(pages, "https://ats.rippling.com/es-419/aspenview/jobs")
        job = site.jobs[0]
        self.assertEqual(job.location, "Remote, Argentina")
        with patch.object(career_sources, "_fetch", web):
            _, description = job.load_details()
        self.assertIn("About", description)
        self.assertIn("React", description)

    def test_rippling_with_no_open_jobs_still_counts_as_a_feed(self):
        pages = {
            "https://ats.rippling.com/api/v2/board/aspenview/jobs?page=0&pageSize=20": {
                "items": [],
                "totalPages": 0,
            }
        }
        site, _ = read_with(pages, "https://ats.rippling.com/es-419/aspenview/jobs")
        self.assertTrue(site.is_feed)
        self.assertEqual(site.jobs, [])


class OwnDomainDetectionTest(unittest.TestCase):
    def test_finds_platform_used_by_company_page(self):
        pages = {
            "https://solvd.com/careers/": '<a href="https://jobs.ashbyhq.com/Solvd/123">Apply</a>',
            "https://api.ashbyhq.com/posting-api/job-board/Solvd": {"jobs": []},
        }
        site, _ = read_with(pages, "https://solvd.com/careers/")
        self.assertTrue(site.is_feed)
        self.assertEqual(site.company, "Solvd")

    def test_ignores_ashby_demo_board(self):
        html = (
            '<script src="https://jobs.ashbyhq.com/ashby-embed-demo-org/embed"></script>'
            '<a href="https://jobs.ashbyhq.com/lazer">Jobs</a>'
        )
        pages = {
            "https://www.lazertechnologies.com/careers": html,
            "https://api.ashbyhq.com/posting-api/job-board/lazer": {"jobs": []},
        }
        site, _ = read_with(pages, "https://www.lazertechnologies.com/careers")
        self.assertEqual(site.company, "lazer")

    def test_workable_job_link_is_not_a_company_name(self):
        html = '<a href="https://apply.workable.com/j/6DEEC05C8A">React Developer</a>'
        site, web = read_with({"https://fusionhit.com/careers/": html}, "https://fusionhit.com/careers/")
        self.assertFalse(site.is_feed)
        self.assertEqual(site.jobs[0].url, "https://apply.workable.com/j/6DEEC05C8A")
        self.assertFalse(any("widget/accounts" in u for u in web.requested))

    def test_bamboohr_marketing_links_are_not_a_company_name(self):
        html = '<img src="https://resources.bamboohr.com/images/footer-logo.png">'
        site, web = read_with({"https://acme.com/careers": html}, "https://acme.com/careers")
        self.assertFalse(site.is_feed)
        self.assertFalse(any("resources.bamboohr.com" in u for u in web.requested))

    def test_reads_teamtailor_rss_from_company_domain(self):
        html = '<script src="https://assets-aws.teamtailor-cdn.com/assets/careersite-0b.js"></script>'
        rss = """<?xml version="1.0"?>
        <rss xmlns:tt="https://teamtailor.com/locations" version="2.0"><channel>
          <item>
            <title>Senior Frontend</title>
            <link>https://careers.zexter.com/jobs/1-frontend</link>
            <description>&lt;p&gt;React&lt;/p&gt;</description>
            <remoteStatus>none</remoteStatus>
            <tt:locations><tt:location><tt:city>Belgrade </tt:city><tt:country>Serbia</tt:country></tt:location></tt:locations>
          </item>
          <item>
            <title>Backend</title>
            <link>https://careers.zexter.com/jobs/2-backend</link>
            <description/>
            <remoteStatus>fully</remoteStatus>
            <tt:locations/>
          </item>
        </channel></rss>"""
        pages = {
            "https://careers.zexter.com/jobs?role=Frontend": html,
            "https://careers.zexter.com/jobs.rss": rss,
        }
        site, _ = read_with(pages, "https://careers.zexter.com/jobs?role=Frontend")
        self.assertTrue(site.is_feed)
        self.assertEqual(site.jobs[0].location, "Belgrade, Serbia")
        self.assertEqual(site.jobs[0].description, "React")
        self.assertEqual(site.jobs[1].location, "Remote")

    def test_reads_recruitee_from_company_domain(self):
        html = '<script src="https://careers-analytics.recruitee.com/a.js"></script>'
        body = {
            "offers": [
                {
                    "title": "Frontend (Remote)",
                    "careers_url": "https://careers.vidiq.com/o/frontend",
                    "location": "Remote job",
                    "locations": [{"name": "Canada", "country": "Canada"}],
                    "description": "<p>About</p>",
                    "requirements": "<p>React</p>",
                }
            ]
        }
        pages = {"https://careers.vidiq.com/": html, "https://careers.vidiq.com/api/offers/": body}
        site, _ = read_with(pages, "https://careers.vidiq.com/")
        self.assertEqual(site.jobs[0].location, "Canada")
        self.assertIn("React", site.jobs[0].description)

    def test_falls_back_to_page_links_when_feed_fails(self):
        html = (
            '<a href="https://jobs.ashbyhq.com/acme">All jobs</a>'
            '<a href="/careers/frontend-engineer">Frontend Engineer</a>'
        )
        site, _ = read_with({"https://acme.com/careers": html}, "https://acme.com/careers")
        self.assertFalse(site.is_feed)
        self.assertEqual(site.jobs[0].title, "Frontend Engineer")


class PlainPageTest(unittest.TestCase):
    def links(self, html, url="https://acme.com/careers"):
        site, _ = read_with({url: html}, url)
        return {job.url: job for job in site.jobs}

    def test_finds_job_links_and_uses_anchor_text_as_title(self):
        jobs = self.links(
            '<a href="/jobs/8397965-senior-frontend-developer"> Senior  Frontend <b>Developer</b> </a>'
        )
        job = jobs["https://acme.com/jobs/8397965-senior-frontend-developer"]
        self.assertEqual(job.title, "Senior Frontend Developer")
        self.assertIsNone(job.location)

    def test_keeps_job_titled_links_outside_a_jobs_folder(self):
        jobs = self.links('<a href="/compliance-specialist/">Compliance Specialist</a>')
        self.assertIn("https://acme.com/compliance-specialist/", jobs)

    def test_keeps_links_to_job_platforms_and_linkedin(self):
        jobs = self.links(
            '<a href="https://www.linkedin.com/jobs/view/4327931326/">Apply</a>'
            '<a href="https://apply.workable.com/j/ABC">Apply</a>'
        )
        self.assertEqual(len(jobs), 2)

    def test_skips_navigation_files_and_other_sites(self):
        jobs = self.links(
            '<a href="/services/devops/">DevOps</a>'
            '<a href="/insights/self-publishing">Engineer stories</a>'
            '<a href="/departments/data-analyst">Data Analyst</a>'
            '<a href="/wp-content/custom-frontend.min.css">x</a>'
            '<a href="/assets/top-software-developer.webp">x</a>'
            '<a href="/careers">Careers</a>'
            '<a href="/jobs/">All jobs</a>'
            '<a href="/careers/benefits">Benefits</a>'
            '<a href="mailto:engineer@acme.com">Mail</a>'
            '<a href="https://other.com/jobs/1-engineer">Elsewhere</a>'
        )
        self.assertEqual(jobs, {})

    def test_same_job_with_tracking_params_is_one_job(self):
        jobs = self.links(
            '<a href="/jobs/1-engineer?utm_source=x">Engineer</a>'
            '<a href="/jobs/1-engineer#apply">Engineer</a>'
        )
        self.assertEqual(list(jobs), ["https://acme.com/jobs/1-engineer"])

    def test_uses_link_address_for_title_when_anchor_says_apply(self):
        jobs = self.links('<a href="/careers/data-engineer">Apply now</a>')
        self.assertEqual(jobs["https://acme.com/careers/data-engineer"].title, "data engineer")

    def test_opens_job_page_for_description_without_scripts(self):
        url = "https://acme.com/careers"
        job_url = "https://acme.com/jobs/1-engineer"
        web = FakeWeb(
            {
                url: '<a href="/jobs/1-engineer">Engineer</a>',
                job_url: "<body><script>var a='PHP';</script><p>Needs React</p></body>",
            }
        )
        with patch.object(career_sources, "_fetch", web):
            job = read_site(url).jobs[0]
            self.assertEqual(job.load_details(), (None, "Needs React"))

    def test_job_page_that_cannot_open_gives_no_description(self):
        url = "https://acme.com/careers"
        web = FakeWeb({url: '<a href="/jobs/1-engineer">Engineer</a>'})
        with patch.object(career_sources, "_fetch", web):
            job = read_site(url).jobs[0]
            self.assertEqual(job.load_details(), (None, None))

    def test_unreadable_page_reports_why(self):
        with self.assertRaises(SiteUnreadable) as caught:
            read_with({}, "https://acme.com/careers")
        self.assertEqual(caught.exception.reason, "page not found (404)")


class NavigationLinksSeenOnRealSitesTest(unittest.TestCase):
    links = PlainPageTest.links

    def test_skips_links_that_are_not_jobs(self):
        not_jobs = [
            ("/careers/talent-pool", "Hire from our team"),
            ("/devhub", "Developer Hub ➜"),
            ("/global-en/jobs/saved-jobs/", "Saved Jobs 0"),
            ("/careers/minders/privacy-policy", "Privacy Policy."),
            ("/careers/inclusion-diversity", "Diversity"),
            ("/en_US/opportunities/Login", "Login"),
            ("/en_US/opportunities/RecommendationMethods", "Recommended Jobs"),
            ("/de_DE/opportunities/SearchJobs/", "Deutsch"),
            ("/en_gl/careers/what-you-can-do-here", "What you can do here"),
            ("/en_gl/careers/how-to-join-us", "How to join us"),
            ("/careers/why-acme/learning-development/", "Professional Development"),
            ("/jobs/get_vacancy/664b4eea41caea6b10667467/candidates/new", "Subir CV"),
            ("/become-recruiter", "Hire Talent"),
        ]
        html = "".join(f'<a href="{path}">{text}</a>' for path, text in not_jobs)
        self.assertEqual(self.links(html), {})

    def test_keeps_job_links_seen_on_real_sites(self):
        real_jobs = [
            ("/careers/qa-automation-engineer", "qa automation engineer"),
            ("/careers/roles/devopsjr/", "Job Description | DevOps Engineer (Jr)"),
            ("/company/careers/positions/payments-apprentice-bogota-colombia/", "apprentice"),
            ("/careers/162l", "162L macOS Systems Engineer"),
            ("/jobs/CC-9149", "9149 - C# Senior"),
            ("/en/careers/81d50158-5f6f-45a9-aabc-a126ecb26517", "PeopleSoft Consultant"),
            ("/jobs/get_vacancy/6ad8aff55d4fd7c415e644db", "Life Advisor"),
            ("/Detail/13862779", "AI Business Analyst"),
            ("/copia-de-virtual-medical-assistant", "UX/UI Designer"),
            ("/careers/talent-acquisition-specialist", "Talent Acquisition Specialist"),
        ]
        html = "".join(f'<a href="{path}">{text}</a>' for path, text in real_jobs)
        self.assertEqual(len(self.links(html)), len(real_jobs))


class JobTitleFromPageTest(unittest.TestCase):
    def test_uses_job_page_title_when_link_text_is_generic(self):
        url = "https://acme.com/careers"
        job_url = "https://www.linkedin.com/jobs/view/4327931326/"
        for text in ("Apply Here", "Info &amp; Apply", "Ver búsqueda →", "Aplica aquí →", "careers"):
            web = FakeWeb(
                {
                    url: f'<a href="{job_url}">{text}</a>',
                    job_url: "<html><head><title>React Dev &amp; Lead</title></head><body>x</body></html>",
                }
            )
            with patch.object(career_sources, "_fetch", web):
                job = read_site(url).jobs[0]
                job.load_details()
            self.assertEqual(job.title, "React Dev & Lead", text)

    def test_keeps_a_real_link_title(self):
        url = "https://acme.com/careers"
        job_url = "https://acme.com/jobs/1-engineer"
        web = FakeWeb(
            {url: f'<a href="{job_url}">Engineer</a>', job_url: "<title>Careers at Acme</title><p>x</p>"}
        )
        with patch.object(career_sources, "_fetch", web):
            job = read_site(url).jobs[0]
            job.load_details()
        self.assertEqual(job.title, "Engineer")


class FeedOnlyTest(unittest.TestCase):
    def test_site_known_as_feed_reports_failure_instead_of_using_page_links(self):
        html = '<a href="https://jobs.ashbyhq.com/acme">Jobs</a><a href="/jobs/1-engineer">Engineer</a>'
        web = FakeWeb({"https://acme.com/careers": html})
        with patch.object(career_sources, "_fetch", web), self.assertRaises(SiteUnreadable) as caught:
            read_site("https://acme.com/careers", feed_only=True)
        self.assertEqual(caught.exception.reason, "page not found (404)")

    def test_hosted_board_known_as_feed_reports_failure(self):
        web = FakeWeb({"https://jobs.lever.co/acme": '<a href="/jobs/1-engineer">Engineer</a>'})
        with patch.object(career_sources, "_fetch", web), self.assertRaises(SiteUnreadable):
            read_site("https://jobs.lever.co/acme", feed_only=True)

    def test_site_that_dropped_its_platform_is_read_from_page(self):
        web = FakeWeb({"https://acme.com/careers": '<a href="/jobs/1-engineer">Engineer</a>'})
        with patch.object(career_sources, "_fetch", web):
            site = read_site("https://acme.com/careers", feed_only=True)
        self.assertFalse(site.is_feed)
        self.assertEqual(len(site.jobs), 1)


class MalformedListingTest(unittest.TestCase):
    def test_workday_skips_a_listing_without_a_link(self):
        base = "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Jobs"

        def web(url, data=None):
            postings = [{"title": "No link"}, {"title": "Fine", "externalPath": "/job/x/1"}]
            return json.dumps({"total": 2, "jobPostings": postings}), url

        with patch.object(career_sources, "_fetch", web):
            site = read_site("https://acme.wd1.myworkdayjobs.com/Jobs")
        self.assertEqual([j.title for j in site.jobs], ["Fine"])


class FetchTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(career_sources, "RETRY_PAUSE_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_explains_common_failures(self):
        cases = {403: "blocked (403)", 429: "blocked (429)", 404: "page not found (404)", 500: "site error (500)"}
        for code, reason in cases.items():
            response = unittest.mock.Mock(status_code=code, ok=False)
            with patch.object(career_sources.requests, "request", return_value=response):
                with self.assertRaises(SiteUnreadable) as caught:
                    career_sources._fetch("https://acme.com")
            self.assertEqual(caught.exception.reason, reason)

    def test_retries_once_when_rate_limited_or_site_is_down(self):
        for code in (429, 503):
            failed = unittest.mock.Mock(status_code=code, ok=False)
            worked = unittest.mock.Mock(status_code=200, ok=True, text="hello", url="https://acme.com")
            with patch.object(career_sources.requests, "request", side_effect=[failed, worked]):
                self.assertEqual(career_sources._fetch("https://acme.com")[0], "hello")

    def test_does_not_retry_a_block_or_missing_page(self):
        for code in (403, 404):
            failed = unittest.mock.Mock(status_code=code, ok=False)
            with patch.object(career_sources.requests, "request", return_value=failed) as request:
                with self.assertRaises(SiteUnreadable):
                    career_sources._fetch("https://acme.com")
            self.assertEqual(request.call_count, 1)

    def test_explains_timeouts(self):
        with patch.object(career_sources.requests, "request", side_effect=career_sources.requests.Timeout()):
            with self.assertRaises(SiteUnreadable) as caught:
                career_sources._fetch("https://acme.com")
        self.assertEqual(caught.exception.reason, "timed out")


if __name__ == "__main__":
    unittest.main()
