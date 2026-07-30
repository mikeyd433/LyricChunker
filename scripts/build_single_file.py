#!/usr/bin/env python3
"""Build the legacy single-file add-on (and optionally the Extension zip)
from the lyric_chunker/ package.

The package (blender_manifest.toml, Blender 4.2+ Extension) is the
canonical source. The dabingabongo.com downloads page ships a single
legacy ``lyric_chunker.py``, produced here by flattening the package:
relative imports are stripped, modules are concatenated in dependency
order, and a ``bl_info`` block generated from blender_manifest.toml is
prepended. Top-level names are unique across modules, so the flattened
file resolves the same names the package does.

Usage:
    python3 scripts/build_single_file.py --out build/lyric_chunker.py
    python3 scripts/build_single_file.py --zip dist/
"""

import argparse
import ast
import re
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "lyric_chunker"

# Concatenation order: every module appears after everything it imports.
MODULE_ORDER = [
    "splitting",
    "manifest",
    "timing_srt",
    "timing_markers",
    "measure",
    "properties",
    "presets",
    "ops_setup",
    "ops_generate",
    "ops_render",
    "ops_verify",
    "ui",
]

HEADER = '''\
# --------------------------------------------------------------------------
# GENERATED FILE — do not edit. Built from the lyric_chunker/ package by
# scripts/build_single_file.py. Edit the package modules instead.
# --------------------------------------------------------------------------
'''

MAIN_BLOCK = '''

if __name__ == "__main__":
    # Re-run friendly for the Text Editor dev loop.
    try:
        unregister()
    except Exception:
        pass
    register()
'''


def read_toml_meta():
    with open(PACKAGE_DIR / "blender_manifest.toml", "rb") as fh:
        meta = tomllib.load(fh)
    return meta


def package_addon_version():
    text = (PACKAGE_DIR / "manifest.py").read_text(encoding="utf-8")
    m = re.search(r'^ADDON_VERSION = "([^"]+)"', text, re.MULTILINE)
    if not m:
        sys.exit("ADDON_VERSION not found in lyric_chunker/manifest.py")
    return m.group(1)


def strip_relative_imports(source):
    """Remove `from . import ...` / `from .mod import ...` statements,
    including parenthesized multi-line forms, using AST line ranges."""
    tree = ast.parse(source)
    drop = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            drop.update(range(node.lineno, node.end_lineno + 1))
    lines = source.splitlines()
    kept = [line for i, line in enumerate(lines, start=1) if i not in drop]
    return "\n".join(kept).rstrip() + "\n"


def bl_info_block(meta):
    version = tuple(int(p) for p in meta["version"].split("."))
    blender_min = tuple(int(p) for p in meta["blender_version_min"].split("."))
    author = meta["maintainer"].split("<")[0].strip()
    return (
        "bl_info = {\n"
        f'    "name": "{meta["name"]}",\n'
        f'    "author": "{author}",\n'
        f'    "version": {version},\n'
        f'    "blender": {blender_min},\n'
        '    "location": "3D Viewport > Sidebar (N) > Lyric Chunker",\n'
        f'    "description": "{meta["tagline"]}",\n'
        '    "category": "Object",\n'
        "}\n"
    )


def build_flat_source():
    meta = read_toml_meta()
    addon_version = package_addon_version()
    if meta["version"] != addon_version:
        sys.exit(
            f"version mismatch: blender_manifest.toml has {meta['version']} "
            f"but manifest.py ADDON_VERSION is {addon_version}"
        )

    parts = [HEADER, bl_info_block(meta)]
    for name in MODULE_ORDER:
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        parts.append(
            f"\n\n# ===== {name}.py "
            + "=" * max(0, 56 - len(name))
            + "\n\n"
            + strip_relative_imports(source)
        )
    init_source = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
    parts.append(
        "\n\n# ===== registration "
        + "=" * 52
        + "\n\n"
        + strip_relative_imports(init_source)
    )
    parts.append(MAIN_BLOCK)
    flat = "".join(parts)

    # The flattened file must be valid Python and must not still contain
    # relative imports.
    compile(flat, "lyric_chunker.py", "exec")
    if re.search(r"^from \.", flat, re.MULTILINE):
        sys.exit("relative import survived flattening")
    return flat, meta


def build_zip(dist_dir, meta):
    """Extension zip: blender_manifest.toml and modules at the zip root."""
    dist_dir.mkdir(parents=True, exist_ok=True)
    out = dist_dir / f"lyric_chunker-{meta['version']}.zip"
    files = sorted(
        p for p in PACKAGE_DIR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(PACKAGE_DIR).as_posix())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="write the flattened single-file add-on here")
    ap.add_argument("--zip", type=Path, help="also build the Extension zip into this directory")
    args = ap.parse_args()
    if not args.out and not args.zip:
        ap.error("nothing to do — pass --out and/or --zip")

    flat, meta = build_flat_source()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(flat, encoding="utf-8")
        print(f"wrote {args.out} ({len(flat.splitlines())} lines, v{meta['version']})")
    if args.zip:
        out = build_zip(args.zip, meta)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
