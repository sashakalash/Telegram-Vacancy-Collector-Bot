import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import career_scanner
import state
from career_sources import Job, SiteRead, SiteUnreadable

URL = "https://acme.com/careers"
WORDS = ["Argentina"]
KEYWORDS = {"include": ["React"], "exclude": ["PHP"]}


def feed(*jobs):
    return SiteRead(list(jobs), "acme", True, "Ashby")


def page(*jobs):
    return SiteRead(list(jobs), "acme.com", False, "page links")


def job(name, location="Argentina", description="React", load_details=None):
    return Job(
        title=name,
        url=f"https://acme.com/jobs/{name}",
        location=location,
        description=description,
        load_details=load_details,
    )


class ScannerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "state.json")
        self.patches = {
            "STATE_FILE": patch.object(state, "STATE_FILE", path),
            "_state": patch.object(state, "_state", {}),
            "_loaded": patch.object(state, "_loaded", False),
        }
        for p in self.patches.values():
            p.start()
            self.addCleanup(p.stop)

        self.read_site = self.start(patch.object(career_scanner, "read_site"))
        self.load_pages = self.start(patch.object(career_scanner, "load_career_pages", return_value=[URL]))
        self.load_words = self.start(patch.object(career_scanner, "load_location_words", return_value=WORDS))
        self.append_rows = self.start(patch.object(career_scanner, "append_career_rows", return_value=True))
        self.write_statuses = self.start(patch.object(career_scanner, "write_career_statuses"))
        self.notify = self.start(patch.object(career_scanner, "send_career_notification", new=AsyncMock(return_value=True)))
        self.alert = self.start(patch.object(career_scanner, "send_career_alert", new=AsyncMock(return_value=True)))
        self.start(patch.object(career_scanner, "NOTIFICATION_PAUSE_SECONDS", 0))
        self.start(patch.object(career_scanner, "DETAILS_PAUSE_SECONDS", 0))

    def start(self, patcher):
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    async def scan(self, *reads):
        self.read_site.side_effect = list(reads)
        return await career_scanner.run_career_scan(KEYWORDS)

    def notified_titles(self):
        return [c.kwargs["title"] for c in self.notify.call_args_list]

    def last_status(self):
        return self.write_statuses.call_args.args[0][URL]


class FirstRunTest(ScannerTestCase):
    async def test_first_run_stays_quiet_and_remembers_jobs(self):
        self.assertTrue(await self.scan(feed(job("a"))))
        self.notify.assert_not_called()
        self.append_rows.assert_not_called()
        self.assertEqual(state.get_career_site(URL)["seen"], {"https://acme.com/jobs/a"})

    async def test_only_a_job_posted_later_is_sent(self):
        await self.scan(feed(job("a")))
        await self.scan(feed(job("a"), job("b")))
        self.assertEqual(self.notified_titles(), ["b"])
        rows = self.append_rows.call_args.args[0]
        self.assertEqual([r.link for r in rows], ["https://acme.com/jobs/b"])

    async def test_first_run_does_not_open_job_pages(self):
        details = unittest.mock.Mock()
        await self.scan(page(job("a", location=None, description=None, load_details=details)))
        details.assert_not_called()

    async def test_feed_with_no_jobs_is_ready_for_its_first_opening(self):
        await self.scan(feed())
        await self.scan(feed(job("a")))
        self.assertEqual(self.notified_titles(), ["a"])

    async def test_page_showing_no_jobs_keeps_next_read_quiet(self):
        await self.scan(page())
        await self.scan(page(job("a")))
        self.notify.assert_not_called()

    async def test_site_added_later_also_starts_quiet(self):
        await self.scan(feed(job("a")))
        other = "https://other.com/careers"
        self.load_pages.return_value = [URL, other]
        await self.scan(feed(job("a")), feed(job("x")))
        self.notify.assert_not_called()


class FilteringTest(ScannerTestCase):
    async def seeded(self):
        await self.scan(feed())

    async def test_cuts_wrong_location_and_never_rechecks_it(self):
        await self.seeded()
        await self.scan(feed(job("a", location="Poland")))
        self.notify.assert_not_called()
        self.assertIn("https://acme.com/jobs/a", state.get_career_site(URL)["seen"])

    async def test_cuts_jobs_without_a_keyword(self):
        await self.seeded()
        await self.scan(feed(job("a", description="Excel")))
        self.notify.assert_not_called()
        self.assertIn("https://acme.com/jobs/a", state.get_career_site(URL)["seen"])

    async def test_exclude_word_checks_title_only(self):
        await self.seeded()
        await self.scan(feed(job("PHP Dev"), job("Frontend", description="React, some PHP")))
        self.assertEqual(self.notified_titles(), ["Frontend"])

    async def test_job_with_no_location_still_gets_through(self):
        await self.seeded()
        await self.scan(feed(job("a", location=None)))
        self.assertEqual(self.notified_titles(), ["a"])

    async def test_details_supply_location_and_description(self):
        await self.seeded()
        await self.scan(
            feed(
                job("near", location=None, description=None, load_details=lambda: ("Argentina", "React")),
                job("far", location=None, description=None, load_details=lambda: ("Poland", "React")),
            )
        )
        self.assertEqual(self.notified_titles(), ["near"])
        self.assertEqual(self.notify.call_args.kwargs["location"], "Argentina")

    async def test_does_not_open_a_job_already_cut_by_location(self):
        await self.seeded()
        details = unittest.mock.Mock()
        await self.scan(feed(job("a", location="Poland", description=None, load_details=details)))
        details.assert_not_called()

    async def test_job_whose_details_fail_is_retried_next_scan(self):
        await self.seeded()

        def broken():
            raise SiteUnreadable("timed out")

        await self.scan(feed(job("a", location=None, description=None, load_details=broken)))
        self.notify.assert_not_called()
        self.assertNotIn("https://acme.com/jobs/a", state.get_career_site(URL)["seen"])
        await self.scan(
            feed(job("a", location=None, description=None, load_details=lambda: ("Argentina", "React")))
        )
        self.assertEqual(self.notified_titles(), ["a"])

    async def test_jobs_past_the_details_limit_wait_for_next_scan(self):
        await self.seeded()
        details = lambda: ("Argentina", "React")
        with patch.object(career_scanner, "MAX_DETAILS_PER_SITE", 1):
            await self.scan(
                feed(
                    job("a", location=None, description=None, load_details=details),
                    job("b", location=None, description=None, load_details=details),
                )
            )
            self.assertEqual(self.notified_titles(), ["a"])
            self.assertNotIn("https://acme.com/jobs/b", state.get_career_site(URL)["seen"])


class SwitchingHowASiteIsReadTest(ScannerTestCase):
    async def test_site_known_as_feed_is_read_as_feed_only(self):
        await self.scan(feed(job("a")))
        self.assertFalse(self.read_site.call_args.kwargs["feed_only"])
        await self.scan(feed(job("a")))
        self.assertTrue(self.read_site.call_args.kwargs["feed_only"])

    async def test_switching_from_feed_to_page_stays_quiet(self):
        await self.scan(feed(job("a")))
        await self.scan(page(job("different-address")))
        self.notify.assert_not_called()
        self.assertFalse(state.get_career_site(URL)["is_feed"])
        await self.scan(page(job("different-address"), job("new")))
        self.assertEqual(self.notified_titles(), ["new"])

    async def test_switching_from_page_to_feed_stays_quiet(self):
        await self.scan(page(job("a")))
        await self.scan(feed(job("different-address")))
        self.notify.assert_not_called()
        self.assertTrue(state.get_career_site(URL)["is_feed"])


class WritingTest(ScannerTestCase):
    async def test_failed_sheet_write_retries_next_scan_without_notifying(self):
        await self.scan(feed())
        self.append_rows.return_value = False
        await self.scan(feed(job("a")))
        self.notify.assert_not_called()
        self.assertNotIn("https://acme.com/jobs/a", state.get_career_site(URL)["seen"])
        self.append_rows.return_value = True
        await self.scan(feed(job("a")))
        self.assertEqual(self.notified_titles(), ["a"])

    async def test_row_holds_title_location_and_description(self):
        await self.scan(feed())
        await self.scan(feed(job("a", description="Knows React")))
        row = self.append_rows.call_args.args[0][0]
        self.assertEqual(row.company, "acme")
        self.assertEqual(row.keywords, ["React"])
        self.assertEqual(row.text, "a\nArgentina\n\nKnows React")


class StatusAndAlertTest(ScannerTestCase):
    async def test_status_describes_a_working_feed(self):
        await self.scan(feed(job("a"), job("b")))
        status = self.last_status()
        self.assertEqual(status.status, "OK - Ashby feed")
        self.assertEqual(status.jobs, 2)

    async def test_status_describes_page_links(self):
        await self.scan(page(job("a")))
        self.assertEqual(self.last_status().status, "OK - page links")

    async def test_status_says_when_nothing_was_found(self):
        await self.scan(page())
        self.assertEqual(self.last_status().status, "No jobs found")

    async def test_site_that_never_worked_only_gets_a_status(self):
        await self.scan(SiteUnreadable("blocked (403)"))
        self.assertEqual(self.last_status().status, "Can't read: blocked (403)")
        self.alert.assert_not_called()

    async def test_working_site_that_breaks_alerts_once(self):
        await self.scan(feed(job("a")))
        await self.scan(SiteUnreadable("blocked (403)"))
        await self.scan(SiteUnreadable("blocked (403)"))
        self.alert.assert_awaited_once_with(URL, "blocked (403)")

    async def test_working_site_suddenly_showing_no_jobs_alerts_once(self):
        await self.scan(page(job("a")))
        await self.scan(page())
        await self.scan(page())
        self.alert.assert_awaited_once_with(URL, "shows no jobs")

    async def test_site_that_recovers_can_alert_again(self):
        await self.scan(page(job("a")))
        await self.scan(page())
        await self.scan(page(job("a")))
        await self.scan(page())
        self.assertEqual(self.alert.await_count, 2)

    async def test_unexpected_error_on_one_site_does_not_stop_the_others(self):
        other = "https://other.com/careers"
        self.load_pages.return_value = [URL, other]
        self.assertTrue(await self.scan(RuntimeError("bug"), feed(job("x"))))
        statuses = self.write_statuses.call_args.args[0]
        self.assertEqual(statuses[URL].status, "Can't read: unexpected error")
        self.assertEqual(statuses[other].status, "OK - Ashby feed")


class NothingToDoTest(ScannerTestCase):
    async def assert_skipped_without_losing_jobs(self, keywords=KEYWORDS):
        self.read_site.side_effect = [feed(job("a"))]
        ran = await career_scanner.run_career_scan(keywords)
        self.assertFalse(ran)
        self.read_site.assert_not_called()

    async def test_no_keywords_skips_scan(self):
        await self.assert_skipped_without_losing_jobs({"include": [], "exclude": []})

    async def test_no_location_words_skips_scan(self):
        self.load_words.return_value = []
        await self.assert_skipped_without_losing_jobs()

    async def test_no_links_yet_skips_scan(self):
        self.load_pages.return_value = []
        await self.assert_skipped_without_losing_jobs()


class StopLoop(Exception):
    pass


class LoopTest(ScannerTestCase):
    async def run_loop(self, scan_result):
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopLoop

        scan = AsyncMock(side_effect=[scan_result])
        with (
            patch.object(career_scanner.asyncio, "sleep", fake_sleep),
            patch.object(career_scanner, "run_career_scan", scan),
            patch.object(career_scanner, "CAREER_SCAN_INTERVAL_HOURS", 24),
            self.assertRaises(StopLoop),
        ):
            await career_scanner.career_scan_loop(KEYWORDS)
        return sleeps

    async def test_finished_scan_waits_a_full_day(self):
        sleeps = await self.run_loop(True)
        self.assertEqual(sleeps[0], 0)
        self.assertAlmostEqual(sleeps[1], 24 * 3600, delta=5)
        self.assertIsNotNone(state.get_last_career_scan())

    async def test_skipped_scan_retries_within_the_hour(self):
        sleeps = await self.run_loop(False)
        self.assertEqual(sleeps[1], career_scanner.RETRY_SECONDS)
        self.assertIsNone(state.get_last_career_scan())

    async def test_crashed_scan_retries_instead_of_killing_the_app(self):
        sleeps = await self.run_loop(RuntimeError("sheets down"))
        self.assertEqual(sleeps[1], career_scanner.RETRY_SECONDS)
        self.assertIsNone(state.get_last_career_scan())


class TimingTest(unittest.TestCase):
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def test_never_scanned_is_due_now(self):
        self.assertEqual(career_scanner.seconds_until_due(None, self.now, 24), 0)

    def test_recent_scan_waits_for_the_rest_of_the_interval(self):
        last = "2026-11-04T06:00:00+00:00"
        self.assertEqual(career_scanner.seconds_until_due(last, self.now, 24), 18 * 3600)

    def test_overdue_scan_runs_now(self):
        last = "2026-11-01T06:00:00+00:00"
        self.assertEqual(career_scanner.seconds_until_due(last, self.now, 24), 0)

    def test_unreadable_time_runs_now(self):
        self.assertEqual(career_scanner.seconds_until_due("garbage", self.now, 24), 0)


if __name__ == "__main__":
    unittest.main()
