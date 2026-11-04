import json
import os
import tempfile
import unittest
from unittest.mock import patch

import state


class CareerStateTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "state.json")
        for name, value in (("STATE_FILE", self.path), ("_state", {}), ("_loaded", False)):
            patcher = patch.object(state, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def reload_from_disk(self):
        state._state = {}
        state._loaded = False

    def test_unknown_site_starts_unseeded(self):
        site = state.get_career_site("https://a.com")
        self.assertEqual(site, {"seeded": False, "seen": set(), "last_jobs": 0, "is_feed": False})

    def test_seen_jobs_and_seeded_flag_survive_a_restart(self):
        state.record_career_site("https://a.com", seen=["j1", "j2"], seeded=True, last_jobs=2, is_feed=True)
        self.reload_from_disk()
        site = state.get_career_site("https://a.com")
        self.assertEqual(site, {"seeded": True, "seen": {"j1", "j2"}, "last_jobs": 2, "is_feed": True})

    def test_recording_adds_to_jobs_already_seen(self):
        state.record_career_site("https://a.com", seen=["j1"])
        state.record_career_site("https://a.com", seen=["j2"])
        self.assertEqual(state.get_career_site("https://a.com")["seen"], {"j1", "j2"})

    def test_recording_without_fields_keeps_them(self):
        state.record_career_site("https://a.com", seeded=True, last_jobs=5)
        state.record_career_site("https://a.com", seen=["j1"])
        site = state.get_career_site("https://a.com")
        self.assertTrue(site["seeded"])
        self.assertEqual(site["last_jobs"], 5)

    def test_oldest_seen_jobs_drop_past_the_cap(self):
        with patch.object(state, "SEEN_CAP_PER_SITE", 2):
            state.record_career_site("https://a.com", seen=["j1", "j2", "j3"])
        self.assertEqual(state.get_career_site("https://a.com")["seen"], {"j2", "j3"})

    def test_last_scan_time_survives_a_restart(self):
        self.assertIsNone(state.get_last_career_scan())
        state.set_last_career_scan("2026-11-04T10:00:00+00:00")
        self.reload_from_disk()
        self.assertEqual(state.get_last_career_scan(), "2026-11-04T10:00:00+00:00")

    def test_existing_telegram_state_is_untouched(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"channels": {"c": {"last_seen_id": 7, "written_ids": [7]}}}, f)
        state.record_career_site("https://a.com", seen=["j1"])
        self.reload_from_disk()
        self.assertEqual(state.get_last_seen("c"), 7)
        self.assertTrue(state.was_written("c", 7))


if __name__ == "__main__":
    unittest.main()
