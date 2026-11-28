from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.profile_storage_manifest import build_manifest, compare_manifests


class ProfileStorageManifestTests(unittest.TestCase):
    def make_profile(self, root: Path) -> Path:
        profile = root / "profile"
        files = {
            "Default/Network/Cookies": b"cookie-secret-placeholder",
            "Default/Local Storage/leveldb/000001.log": b"local-storage-placeholder",
            "Default/IndexedDB/https_storage.money_0.indexeddb.leveldb/000001.log": b"indexeddb-placeholder",
            "Default/Service Worker/Database/000001.log": b"service-worker-placeholder",
            "Default/Session Storage/000001.log": b"session-storage-placeholder",
            "Default/Preferences": b"unrelated-file-not-in-manifest",
        }
        for relative, content in files.items():
            path = profile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return profile

    def test_manifest_inventories_storage_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.make_profile(Path(directory))
            manifest = build_manifest(profile)
            categories = manifest["category_file_counts"]
            self.assertEqual(categories["cookies"], 1)
            self.assertEqual(categories["local_storage"], 1)
            self.assertEqual(categories["indexed_db"], 1)
            self.assertEqual(categories["service_worker"], 1)
            self.assertEqual(categories["session_storage"], 1)
            serialized = json.dumps(manifest)
            self.assertNotIn("cookie-secret-placeholder", serialized)
            self.assertNotIn("local-storage-placeholder", serialized)
            self.assertNotIn("indexeddb-placeholder", serialized)

    def test_restored_profile_matches_saved_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.make_profile(Path(directory))
            expected = build_manifest(profile)
            actual = build_manifest(profile)
            report = compare_manifests(expected, actual)
            self.assertEqual(report["status"], "MATCH")
            self.assertEqual(report["expected_file_count"], 5)

    def test_changed_storage_file_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.make_profile(Path(directory))
            expected = build_manifest(profile)
            (profile / "Default/Network/Cookies").write_bytes(b"changed-cookie-db")
            actual = build_manifest(profile)
            report = compare_manifests(expected, actual)
            self.assertEqual(report["status"], "MISMATCH")
            self.assertIn("Default/Network/Cookies", report["changed_files"])

    def test_missing_and_added_storage_files_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.make_profile(Path(directory))
            expected = build_manifest(profile)
            (profile / "Default/Session Storage/000001.log").unlink()
            extra = profile / "Default/Shared Storage/000001.log"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b"extra")
            actual = build_manifest(profile)
            report = compare_manifests(expected, actual)
            self.assertEqual(report["status"], "MISMATCH")
            self.assertIn("Default/Session Storage/000001.log", report["missing_files"])
            self.assertIn("Default/Shared Storage/000001.log", report["added_files"])


if __name__ == "__main__":
    unittest.main()
