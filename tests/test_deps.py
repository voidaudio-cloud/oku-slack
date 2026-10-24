"""Tests for scripts/check_deps.py: synthetic manifests in tmp_path (never the repo), plus the real scan."""
import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_deps", REPO / "scripts" / "check_deps.py")
check_deps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_deps)


def _write_manifests(root, bridge, wheel):
    (root / "requirements.txt").write_text("\n".join(bridge) + "\n", encoding="utf-8")
    (root / "requirements-wheel.txt").write_text("\n".join(wheel) + "\n", encoding="utf-8")
    (root / "requirements-dev.txt").write_text("", encoding="utf-8")


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr(check_deps, "ROOT", tmp_path)
    return tmp_path


def test_fully_declared_passes(synthetic):
    _write_manifests(synthetic, bridge=["requests>=2.31"], wheel=["aiohttp>=3.9", "pillow>=10", "requests>=2.31"])
    found = [
        ("oku_slack/core.py", 1, "requests", "bridge", False),
        ("oku_slack/wheel/server.py", 1, "aiohttp", "wheel", False),
        ("oku_slack/wheel/render.py", 2, "PIL", "wheel", False),
    ]
    assert check_deps.check(found) == []


def test_one_missing_declaration_fails(synthetic):
    _write_manifests(synthetic, bridge=["requests>=2.31"], wheel=["aiohttp>=3.9", "requests>=2.31"])
    found = [("oku_slack/wheel/render.py", 2, "PIL", "wheel", False)]
    problems = check_deps.check(found)
    assert len(problems) == 1
    assert "PIL" in problems[0] and "pillow" in problems[0] and "render.py:2" in problems[0]


def test_bridge_import_not_satisfied_by_wheel_manifest(synthetic):
    # bridge runtime must be checked against requirements.txt only (plus dev), not the wheel manifest
    _write_manifests(synthetic, bridge=[], wheel=["requests>=2.31"])
    problems = check_deps.check([("oku_slack/core.py", 1, "requests", "bridge", False)])
    assert len(problems) == 1


def test_optional_guarded_import_is_not_required(synthetic):
    _write_manifests(synthetic, bridge=[], wheel=[])
    found = [("oku_slack/wheel/render.py", 3, "fontTools", "wheel", True)]
    assert check_deps.check(found) == []


def test_missing_manifest_is_reported(synthetic):
    with pytest.raises(FileNotFoundError):
        check_deps.read_declared(["requirements-dev.txt"])


def test_guarded_import_detection_is_ast_based(synthetic):
    src = (
        "try:\n    import requests\nexcept ImportError:\n    requests = None\n"
        "import aiohttp\n"
    )
    result = {mod: optional for mod, _, optional in check_deps.top_level_imports(src)}
    assert result == {"requests": True, "aiohttp": False}


def test_real_manifests_satisfy_real_scan():
    found = check_deps.scan()
    assert found, "expected third-party imports under oku_slack/"
    assert check_deps.check(found) == []


def test_real_wheel_runtime_declares_requests():
    declared = check_deps.read_declared(["requirements-wheel.txt"])
    assert "requests" in declared and "aiohttp" in declared and "pillow" in declared
