import unittest
from unittest.mock import AsyncMock, patch

import notifier


class CareerNotificationTest(unittest.IsolatedAsyncioTestCase):
    async def send(self, **overrides):
        job = {
            "company": "acme",
            "title": "Frontend <Engineer> & Lead",
            "location": "Remote, Argentina",
            "keywords": ["React", "Next js"],
            "link": "https://a.com/jobs/1?x=1&y='2'",
        }
        job.update(overrides)
        bot = AsyncMock()
        with patch.object(notifier, "_get_bot", return_value=bot):
            result = await notifier.send_career_notification(**job)
        return result, bot.send_message.call_args.kwargs

    async def test_escapes_text_so_telegram_accepts_it(self):
        ok, sent = await self.send()
        self.assertTrue(ok)
        self.assertEqual(sent["parse_mode"], "HTML")
        self.assertIn("Frontend &lt;Engineer&gt; &amp; Lead", sent["text"])
        self.assertIn("href='https://a.com/jobs/1?x=1&amp;y=&#x27;2&#x27;'", sent["text"])

    async def test_shows_company_location_and_keywords(self):
        _, sent = await self.send()
        self.assertIn("acme", sent["text"])
        self.assertIn("Remote, Argentina", sent["text"])
        self.assertIn("#React | #Next_js", sent["text"])

    async def test_job_without_location_says_so(self):
        _, sent = await self.send(location=None)
        self.assertIn("not listed", sent["text"])

    async def test_failure_returns_false(self):
        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("telegram down")
        with patch.object(notifier, "_get_bot", return_value=bot):
            ok = await notifier.send_career_notification("a", "t", None, [], "https://a.com")
        self.assertFalse(ok)


class CareerAlertTest(unittest.IsolatedAsyncioTestCase):
    async def test_names_the_site_and_problem(self):
        bot = AsyncMock()
        with patch.object(notifier, "_get_bot", return_value=bot):
            ok = await notifier.send_career_alert("https://a.com/?x=1&y=2", "blocked (403)")
        self.assertTrue(ok)
        text = bot.send_message.call_args.kwargs["text"]
        self.assertIn("https://a.com/?x=1&amp;y=2", text)
        self.assertIn("blocked (403)", text)


if __name__ == "__main__":
    unittest.main()
