import pytest

from nursebot import updater
from nursebot.db import DB
from nursebot.runtime import Life, Runtime


def test_version_compare_and_platform_asset():
    p = updater.parse_version
    assert p("v0.1.10") > p("0.1.2") > p("v0.1.0") and p("1.0.0-rc1") == (1, 0, 0)
    assets = [{"name": "NTULineBot-mac.dmg"}, {"name": "NTULineBot-Setup.exe"}]
    assert updater.pick_asset(assets, "win32")["name"].endswith(".exe")
    assert updater.pick_asset(assets, "darwin")["name"].endswith(".dmg")
    assert updater.pick_asset(assets, "linux") is None


def test_update_check_flags_newer_release_only_for_real_builds(tmp_path, monkeypatch):
    rt = Runtime(DB(tmp_path / "t.db"))
    rel = {"tag_name": "v9.0.0", "html_url": "u", "assets": [{"name": "x.exe", "size": 5}, {"name": "x.dmg", "size": 5}]}

    class R:
        def raise_for_status(self): pass
        def json(self): return rel
    monkeypatch.setattr(rt.updater.http, "get", lambda *a, **k: R())
    monkeypatch.setattr(updater, "VERSION", "0.1.0")
    assert rt.updater.check()["available"] is True
    monkeypatch.setattr(updater, "VERSION", "0.0.0-dev")   # source checkouts never nag
    assert rt.updater.check()["available"] is False


def test_activity_state_transitions(tmp_path):
    rt = Runtime(DB(tmp_path / "t.db"))
    rt.llm._hcache = (1e18, {"chat": True, "embed": True})   # pretend both models are healthy
    assert rt.activity()["state"] == "offline"
    rt.life = Life.RUNNING
    assert rt.activity()["state"] == "idle"
    rt.llm.active["embed"] = 1
    assert rt.activity()["state"] == "searching"
    rt.llm.active["chat"] = 1
    assert rt.activity()["state"] == "generating"
    rt.llm._hcache = (1e18, {"chat": False, "embed": True})
    rt.llm.active["chat"] = 0
    assert rt.activity()["state"] == "loading"
