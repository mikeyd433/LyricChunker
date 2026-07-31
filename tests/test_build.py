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
    modules.add("comp/settings_gen")
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


def test_comp_flattening_is_self_contained():
    flat = build.build_comp_source()
    compile(flat, "generate_comp.py", "exec")
    # The repo-load section must be fully replaced by inlined modules.
    assert "_PACKAGE_DIR" not in flat
    assert "spec_from_file_location" not in flat
    for name in ("def read_manifest", "def generate_line_setting", "def main"):
        assert name in flat
    assert "from ." not in flat


def test_bundle_zip_contents(tmp_path):
    import zipfile

    flat, meta = build.build_flat_source()
    comp = build.build_comp_source()
    out = build.build_bundle(tmp_path / "bundle.zip", flat, comp, meta)
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == [
            "Generate Comps.bat", "LyricChunker_BuildComp.py", "README.txt",
            "generate_comp.py", "lyric_chunker.py",
        ]
        assert zf.read("lyric_chunker.py").decode() == flat
        assert b"\r\n" in zf.read("Generate Comps.bat")
    # Deterministic: rebuilding yields identical bytes.
    again = build.build_bundle(tmp_path / "bundle2.zip", flat, comp, meta)
    assert out.read_bytes() == again.read_bytes()
