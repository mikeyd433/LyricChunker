import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "build_single_file", REPO_ROOT / "scripts" / "build_single_file.py"
)
build = importlib.util.module_from_spec(spec)
sys.modules["build_single_file"] = build
spec.loader.exec_module(build)


def test_module_order_covers_package():
    modules = {
        p.stem
        for p in (REPO_ROOT / "lyric_chunker").glob("*.py")
        if p.stem != "__init__"
    }
    assert set(build.MODULE_ORDER) == modules


def test_flat_build_compiles_and_carries_bl_info():
    flat, meta = build.build_flat_source()
    compile(flat, "lyric_chunker.py", "exec")
    assert "bl_info = {" in flat
    assert f'"version": {tuple(int(p) for p in meta["version"].split("."))}' in flat
    assert "from ." not in flat
    # Registration must survive flattening.
    assert "def register():" in flat
    assert "def unregister():" in flat


def test_versions_agree():
    meta = build.read_toml_meta()
    assert meta["version"] == build.package_addon_version()
