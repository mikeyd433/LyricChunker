#!/usr/bin/env python3
"""Sync lyric_chunker.py into the Dabingabongo downloads page.

Copies the add-on into <site>/downloads/ and updates the "lyric-chunker"
entry in <site>/downloads.json: version (read from bl_info), file size,
and updated date. When the version changed, a new changelog entry is
prepended using the triggering commit's subject line as the note.
"""

import argparse
import datetime
import json
import re
import shutil
from pathlib import Path

ITEM_ID = "lyric-chunker"


def parse_version(addon_text):
    m = re.search(
        r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', addon_text
    )
    if not m:
        raise SystemExit("could not find the bl_info version tuple in the add-on")
    return ".".join(m.groups())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("addon", help="path to lyric_chunker.py")
    ap.add_argument("site", help="path to the Dabingabongo checkout")
    ap.add_argument("--note", default="", help="changelog note (commit subject)")
    ap.add_argument("--commit-sha", default="", help="LyricChunker commit sha")
    args = ap.parse_args()

    addon = Path(args.addon)
    site = Path(args.site)
    manifest_path = site / "downloads.json"

    version = parse_version(addon.read_text(encoding="utf-8"))
    size_kb = max(1, round(addon.stat().st_size / 1024))
    today = datetime.date.today().isoformat()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item = next(
        (i for i in manifest.get("items", []) if i.get("id") == ITEM_ID), None
    )
    if item is None:
        raise SystemExit(f'no item with "id": "{ITEM_ID}" in {manifest_path}')

    dest = site / "downloads" / "lyric_chunker.py"
    if (
        dest.exists()
        and dest.read_bytes() == addon.read_bytes()
        and item.get("version") == version
    ):
        print(f"already in sync at v{version} — nothing to update")
        return

    dest.parent.mkdir(exist_ok=True)
    shutil.copyfile(addon, dest)

    previous = item.get("version")
    item["version"] = version
    item["updated"] = today
    for d in item.get("downloads", []):
        if d.get("url", "").endswith("lyric_chunker.py"):
            d["size"] = f"{size_kb} KB"

    if version != previous:
        note = args.note.strip().splitlines()[0].strip() if args.note.strip() else ""
        note = note or "Synced from LyricChunker main."
        if args.commit_sha:
            note += f" (LyricChunker@{args.commit_sha[:7]})"
        item.setdefault("changelog", []).insert(
            0, {"version": version, "date": today, "notes": [note]}
        )

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"synced v{version} ({size_kb} KB), manifest previously at v{previous}")


if __name__ == "__main__":
    main()
