"""Load package modules by file path so tests never execute
lyric_chunker/__init__.py (which imports bpy)."""

import importlib.util
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "lyric_chunker"


def load(name):
    key = f"lc_test_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, PACKAGE_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module
