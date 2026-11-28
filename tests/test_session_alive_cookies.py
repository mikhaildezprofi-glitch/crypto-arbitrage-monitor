from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.check_session_alive_cookies import inspect_profile


class SessionAliveCookieTests(unittest.TestCase):
    def create_cookie_db(self, profile: Path, rows):
        database = profile / "Default" / "Network" / "Cookies"
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT)"
            )
            connection.executemany(
                "INSERT INTO cookies (host_key, name, value) VALUES (?, ?, ?)",
                rows,
            )
        return database

    def test_requires_session_alive_for_both_provider_domains(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            profile.mkdir()
            self.create_cookie_db(profile, [
                (".storage.money", "session_alive", "do-not-expose-cookie-value"),
                (".sberkassa.site", "session_alive", "another-secret-cookie-value"),
            ])
            report = inspect_profile(profile)
            self.assertTrue(report["all_pages_have_session_alive"])
            self.assertTrue(report["pages"]["money_storage"]["session_alive_present"])
            self.assertTrue(report["pages"]["sberkassa_deals"]["session_alive_present"])
            self.assertTrue(report["pages"]["sberkassa_exchange"]["session_alive_present"])
            serialized = json.dumps(report)
            self.assertNotIn("do-not-expose-cookie-value", serialized)
            self.assertNotIn("another-secret-cookie-value", serialized)

    def test_missing_provider_cookie_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            profile.mkdir()
            self.create_cookie_db(profile, [
                (".storage.money", "session_alive", "secret"),
            ])
            report = inspect_profile(profile)
            self.assertFalse(report["all_pages_have_session_alive"])
            self.assertFalse(report["pages"]["sberkassa_exchange"]["session_alive_present"])

    def test_unrelated_cookie_does_not_count(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            profile.mkdir()
            self.create_cookie_db(profile, [
                (".storage.money", "other_cookie", "secret"),
                (".sberkassa.site", "other_cookie", "secret"),
            ])
            report = inspect_profile(profile)
            self.assertFalse(report["all_pages_have_session_alive"])


if __name__ == "__main__":
    unittest.main()
