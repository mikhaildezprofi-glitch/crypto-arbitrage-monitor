#!/usr/bin/env python3
"""Inventory Chromium site-storage files without reading or publishing their contents.

The manifest stores only relative paths, byte sizes, and SHA-256 digests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CATEGORIES = {
    "cookies": {"cookies", "cookies-journal"},
    "local_storage": {"local storage"},
    "indexed_db": {"indexeddb"},
    "service_worker": {"service worker"},
    "session_storage": {"session storage"},
    "shared_storage": {"shared storage"},
    "web_storage": {"webstorage"},
}


def category_for(path: Path) -> str | None:
    parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if name in CATEGORIES["cookies"]:
        return "cookies"
    for category, markers in CATEGORIES.items():
        if category == "cookies":
            continue
        if any(marker in parts for marker in markers):
            return category
    return None


def build_manifest(profile_dir: Path) -> dict[str, Any]:
    if not profile_dir.is_dir():
        raise FileNotFoundError("Chromium profile directory is missing")
    files = []
    for path in sorted(profile_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        category = category_for(path.relative_to(profile_dir))
        if category is None:
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append({
            "path": path.relative_to(profile_dir).as_posix(),
            "category": category,
            "size": path.stat().st_size,
            "sha256": digest.hexdigest(),
        })
    counts = {category: 0 for category in CATEGORIES}
    for item in files:
        counts[item["category"]] += 1
    return {
        "schema_version": 1,
        "file_count": len(files),
        "category_file_counts": counts,
        "files": files,
    }


def compare_manifests(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_files = {
        item["path"]: item for item in expected.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    actual_files = {
        item["path"]: item for item in actual.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    missing = sorted(set(expected_files) - set(actual_files))
    added = sorted(set(actual_files) - set(expected_files))
    changed = sorted(
        path for path in set(expected_files) & set(actual_files)
        if expected_files[path].get("size") != actual_files[path].get("size")
        or expected_files[path].get("sha256") != actual_files[path].get("sha256")
        or expected_files[path].get("category") != actual_files[path].get("category")
    )
    return {
        "status": "MATCH" if not (missing or added or changed) else "MISMATCH",
        "expected_file_count": len(expected_files),
        "actual_file_count": len(actual_files),
        "missing_files": missing,
        "added_files": added,
        "changed_files": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--profile-dir", required=True)
    create.add_argument("--output", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--profile-dir", required=True)
    compare.add_argument("--expected", required=True)
    compare.add_argument("--report", required=True)
    args = parser.parse_args()

    actual = build_manifest(Path(args.profile_dir))
    if args.command == "create":
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(actual, sort_keys=True, indent=2) + chr(10), encoding="utf-8")
        print(
            "PROFILE_STORAGE_MANIFEST_CREATED files=%d categories=%s"
            % (actual["file_count"], json.dumps(actual["category_file_counts"], sort_keys=True)),
            flush=True,
        )
        return 0

    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    report = compare_manifests(expected, actual)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + chr(10), encoding="utf-8")
    print(
        "PROFILE_STORAGE_RESTORE_CHECK=%s expected=%d actual=%d missing=%d added=%d changed=%d"
        % (
            report["status"],
            report["expected_file_count"],
            report["actual_file_count"],
            len(report["missing_files"]),
            len(report["added_files"]),
            len(report["changed_files"]),
        ),
        flush=True,
    )
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
